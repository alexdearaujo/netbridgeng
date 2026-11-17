"""
Junos -> bridge contract.

The bridge page reads the EOS JSON shape (show ... | json). This module maps the Junos replies the
collector gathers (XML converted to the '| display json' dict shape) onto those same paths, so the
page stays a single renderer and a new vendor is only a collector plus an adapter.

Junos does not report some values the EOS page uses; those are left as None rather than invented:
  - per-sensor setpoint / alert / critical limits (show chassis environment has no thresholds)
  - fan speed as a percent (Junos gives text: 'Spinning at normal speed', or RPM on newer boxes)
  - PSU output watts / capacity
  - OSPF retransmission and state-change counters
Chassis alarms stand in for EOS's system temperature / cooling status lines.

Every section lookup goes through find(), which searches depth-first for a tag, so the same code
reads single-RE replies and multi-RE / Virtual Chassis replies (multi-routing-engine-results/...).
"""

import re
import time
from typing import Any

# ---------------------------------------------------------------------------------------------
# helpers for the Junos-JSON shape: every value is a list; leaves are [{"data": ..., "attributes": ...}]
# ---------------------------------------------------------------------------------------------


def find(obj: Any, tag: str) -> list:
    """First occurrence of tag anywhere under obj (depth-first). Returns its list, or []."""
    if isinstance(obj, dict):
        if tag in obj and isinstance(obj[tag], list):
            return obj[tag]
        for v in obj.values():
            r = find(v, tag)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find(v, tag)
            if r:
                return r
    return []


def first(obj: Any, tag: str) -> dict:
    """First branch node for tag (a dict), or {}."""
    lst = find(obj, tag)
    return lst[0] if lst and isinstance(lst[0], dict) and "data" not in lst[0] else {}


def val(node: dict, tag: str, default=None):
    """Text of a direct leaf child."""
    lst = node.get(tag) if isinstance(node, dict) else None
    if not lst:
        return default
    f = lst[0]
    if isinstance(f, dict) and "data" in f:
        return f["data"] if f["data"] != "" else default
    return default


def attr(node: dict, tag: str, name: str, default=None):
    lst = node.get(tag) if isinstance(node, dict) else None
    if lst and isinstance(lst[0], dict):
        return (lst[0].get("attributes") or {}).get(name, default)
    return default


def num(v, default=0):
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return float(v)
        except (TypeError, ValueError):
            m = re.search(r"-?\d+(?:\.\d+)?", str(v))
            return float(m.group()) if m else default


def section_error(parsed: dict, key: str) -> str | None:
    v = parsed.get(key)
    return v.get("_error") if isinstance(v, dict) and v.get("_error") else None


_DUR = re.compile(r"(?:(\d+)w)?(?:(\d+)d)?\s*(?:(\d+):)?(\d+):(\d+)$")
_WORDS = re.compile(r"(\d+)\s*(week|day|hour|minute|second)s?", re.I)


def duration_seconds(text: str | None, seconds_attr: str | None = None) -> int:
    """Junos elapsed/up times: the junos:seconds attribute when present, else '1w2d 3:04:05',
    '3:04:05', '12:34', or '12 days, 3 hours, 4 minutes'."""
    if seconds_attr not in (None, ""):
        try:
            return int(seconds_attr)
        except ValueError:
            pass
    if not text:
        return 0
    t = text.strip()
    m = _DUR.match(t)
    if m:
        w, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
        return w * 604800 + d * 86400 + h * 3600 + mi * 60 + s
    unit = {"week": 604800, "day": 86400, "hour": 3600, "minute": 60, "second": 1}
    tot = sum(int(n) * unit[u.lower()] for n, u in _WORDS.findall(t))
    if tot:
        return tot
    m = re.match(r"^(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?$", t)   # '12w3d' / '2d4h' (long uptimes drop the clock)
    if m and any(m.groups()):
        w, d, h = (int(x) if x else 0 for x in m.groups())
        return w * 604800 + d * 86400 + h * 3600
    return 0


def speed_bps(text: str | None) -> int:
    """'10Gbps', '1000mbps', '100G', 'Auto', 'Unlimited' -> bits per second (0 when not a rate)."""
    if not text:
        return 0
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:bps|b/s)?\s*$", text.strip(), re.I)
    if not m:
        return 0
    mult = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9, "t": 1e12}[m.group(2).lower()]
    return int(float(m.group(1)) * mult)


# Physical, front-panel-ish interfaces: what EOS 'show interfaces status' would list.
_PHYS = re.compile(r"^(?:(?:ge|xe|et|mge|fe|xle|fte)-\d+/\d+/\d+(?::\d+)?|ae\d+|em\d+|fxp\d+|me\d+|re\d+:\w+)$")


def phys_name(ifname: str | None) -> str:
    """Drop the unit: 'xe-0/0/1.0' -> 'xe-0/0/1' (LLDP and OSPF report logical names)."""
    return (ifname or "").split(".")[0]


def strip_port(addr: str | None) -> str:
    """'10.0.0.1+179' -> '10.0.0.1'."""
    return (addr or "").split("+")[0]


# ---------------------------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------------------------


def _version(p: dict) -> dict:
    sw = first(p.get("version"), "software-information")
    rei = p.get("routing_engine")
    engines = find(rei, "route-engine")
    master = next((e for e in engines if re.match(r"master", val(e, "mastership-state", "") or "", re.I)), engines[0] if engines else {})
    chassis = first(p.get("hardware"), "chassis")

    ver = val(sw, "junos-version")
    if not ver:   # pre-15 Junos: the version is in the package comments, 'JUNOS Base OS boot [12.3R12.4]'
        for pkg in sw.get("package-information", []):
            m = re.search(r"\[([^\]]+)\]", val(pkg, "comment", "") or "")
            if m:
                ver = m.group(1)
                break

    up = duration_seconds(val(master, "up-time"), attr(master, "up-time", "junos:seconds"))
    dram = num(val(master, "memory-dram-size"), 0)            # '2048 MB'
    util = num(val(master, "memory-buffer-utilization"), None)
    mem_total = int(dram * 1024) if dram else None            # kB, like EOS
    mem_free = int(mem_total * (1 - util / 100)) if mem_total and util is not None else None
    return {
        "hostname": val(sw, "host-name") or "",
        "modelName": (val(sw, "product-model") or val(chassis, "description") or "").upper(),
        "version": ver or "",
        "serialNumber": val(chassis, "serial-number") or "",
        "uptime": up,
        "bootupTimestamp": time.time() - up if up else None,
        "memTotal": mem_total,
        "memFree": mem_free,
        "vendor": "Juniper",
    }, master


def _proc(master: dict) -> dict:
    idle = val(master, "cpu-idle")
    if idle is None:
        return {}
    return {"cpuInfo": {"%Cpu(s)": {
        "idle": num(idle, 0), "user": num(val(master, "cpu-user"), 0), "system": num(val(master, "cpu-system"), 0),
    }}}


def _interfaces(p: dict) -> tuple[dict, dict]:
    statuses, counters = {}, {}
    for pi in find(p.get("interfaces"), "physical-interface"):
        name = val(pi, "name", "")
        if not _PHYS.match(name):
            continue
        admin = (val(pi, "admin-status") or "").lower()
        oper = (val(pi, "oper-status") or "").lower()
        bw = speed_bps(val(pi, "speed"))
        statuses[name] = {
            "description": val(pi, "description") or "",
            "linkStatus": "disabled" if admin == "down" else ("connected" if oper == "up" else "notconnect"),
            "lineProtocolStatus": oper or "down",
            "bandwidth": bw,
            "interfaceType": val(pi, "if-media-type") or val(pi, "link-level-type") or "",
            "duplex": "duplexFull" if re.search(r"full", val(pi, "duplex", "") or val(pi, "link-mode", "") or "", re.I) else "",
            "vlanInformation": {"interfaceMode": "routed"},
        }
        ts = first(pi, "traffic-statistics")
        if ts and val(ts, "input-bytes") is not None:
            ie, oe = first(pi, "input-error-list"), first(pi, "output-error-list")
            counters[name] = {
                "inOctets": num(val(ts, "input-bytes"), 0),
                "outOctets": num(val(ts, "output-bytes"), 0),
                "inDiscards": num(val(ie, "input-drops"), 0),
                "outDiscards": num(val(oe, "output-drops"), 0),
            }
    return statuses, counters


def _lldp(p: dict) -> list:
    out = []
    for n in find(p.get("lldp"), "lldp-neighbor-information"):
        # lldp-local-interface on ELS / newer code; older code gives the name in lldp-local-port-id
        local = val(n, "lldp-local-interface") or val(n, "lldp-local-port-id") or ""
        rport = val(n, "lldp-remote-port-id") or ""
        rdesc = val(n, "lldp-remote-port-description") or ""
        if rport.isdigit() and rdesc:   # the far end sent an ifIndex as port ID
            rport = rdesc
        out.append({
            "port": phys_name(local),
            "neighborDevice": val(n, "lldp-remote-system-name") or val(n, "lldp-remote-chassis-id") or "",
            "neighborPort": rport,
            "ttl": 120,
        })
    return out


def _bgp(p: dict) -> dict:
    info = first(p.get("bgp"), "bgp-information")
    ro = first(p.get("routing_options"), "routing-options")
    asn = val(first(ro, "autonomous-system"), "as-number") or ""
    rid = val(ro, "router-id") or ""
    now = time.time()
    peers = {}
    for bp in info.get("bgp-peer", []) if info else []:
        ip = strip_port(val(bp, "peer-address"))
        if not ip:
            continue
        state = val(bp, "peer-state", "") or ""
        rx = acc = 0
        for rib in bp.get("bgp-rib", []):
            rx += num(val(rib, "received-prefix-count"), 0)
            acc += num(val(rib, "accepted-prefix-count"), 0)
        el = duration_seconds(val(bp, "elapsed-time"), attr(bp, "elapsed-time", "junos:seconds"))
        peers[ip] = {
            "peerState": "Established" if state.lower().startswith("establ") else state,
            "asn": str(val(bp, "peer-as") or ""),
            "description": val(bp, "description") or "",
            "prefixReceived": rx,
            "prefixAccepted": acc,
            "upDownTime": now - el if el else now,
            "msgReceived": num(val(bp, "input-messages"), 0),
            "msgSent": num(val(bp, "output-messages"), 0),
            "outMsgQueue": num(val(bp, "route-queue-count"), 0),
            "inMsgQueue": 0,
            "flaps": num(val(bp, "flap-count"), 0),
        }
    if not peers and not asn:
        return {}
    return {"vrfs": {"default": {"routerId": rid, "asn": str(asn), "peers": peers}}}


def _ospf(p: dict) -> dict:
    entries = []
    for n in find(p.get("ospf"), "ospf-neighbor"):
        addr = val(n, "neighbor-address") or ""
        dr, bdr = val(n, "dr-address"), val(n, "bdr-address")
        if dr in (None, "0.0.0.0") and bdr in (None, "0.0.0.0"):
            drs = "P2P"
        elif addr and addr == dr:
            drs = "DR"
        elif addr and addr == bdr:
            drs = "BDR"
        else:
            drs = "DROTHER"
        entries.append({
            "routerId": val(n, "neighbor-id") or "",
            "interfaceAddress": addr,
            "interfaceName": phys_name(val(n, "interface-name")),
            "adjacencyState": (val(n, "ospf-neighbor-state") or "").lower(),
            "priority": num(val(n, "neighbor-priority"), 0),
            "drState": drs,
            "details": {
                "areaId": val(n, "ospf-area") or "0.0.0.0",
                "upTime": duration_seconds(val(n, "neighbor-up-time"), attr(n, "neighbor-up-time", "junos:seconds")),
            },
        })
    if not entries and section_error(p, "ospf"):
        return {}
    return {"vrfs": {"default": {"instList": {"1": {"ospfNeighborEntries": entries}}}}}


def _routes(p: dict) -> dict:
    tables = find(p.get("routes"), "route-table")
    inet0 = next((t for t in tables if val(t, "table-name") == "inet.0"), None)
    if not inet0:
        return {}
    protos = {(val(pr, "protocol-name") or "").upper(): pr for pr in inet0.get("protocols", [])}
    def active(name):
        pr = protos.get(name)
        return num(val(pr, "active-route-count"), 0) if pr else 0
    total = num(val(inet0, "active-route-count"), None)
    if total is None:
        total = num(val(inet0, "total-route-count"), 0)
    return {"vrfs": {"default": {
        "totalRoutes": total,
        "bgpCounts": {"bgpTotal": active("BGP")},
        # Junos route summary has no intra/inter/external split; one bucket the page draws as 'ospf'
        "ospfCounts": {"ospfTotal": active("OSPF")} if "OSPF" in protos else {},
    }}}


_PSU_NUM = re.compile(r"(?:power supply|pem|psm|psu)\s*(\d+)", re.I)
# a power supply item itself ('PEM 0', 'PSM 3', 'FPC 0 Power Supply 1'), not a sensor on one ('... Temp Sensor')
_PSU_ITEM = re.compile(r"^(?:FPC\s*\d+\s+)?(?:power supply|pem|psm|psu)\s*\d+$", re.I)
_EMPTY = re.compile(r"^(absent|empty|not present)$", re.I)


def _environment(p: dict) -> dict:
    env = {"sensors": [], "fans": [], "power_supplies": [], "ambient_temp": None, "airflow": None,
           "cooling_status": None, "temp_status": None}
    items = find(p.get("environment"), "environment-item")
    cls = ""
    for it in items:
        name = val(it, "name", "") or ""
        cls = val(it, "class") or cls          # some releases print <class> only on a group's first item
        status = val(it, "status", "") or ""
        if _EMPTY.match(status):               # unpopulated slots (MX PEM / fan slots)
            continue
        comment = val(it, "comment") or ""
        celsius = attr(it, "temperature", "junos:celsius")
        if celsius is None:
            m = re.search(r"(-?\d+)\s*degrees C", val(it, "temperature", "") or "")
            celsius = m.group(1) if m else None
        pm = _PSU_NUM.search(name)

        # Power items: on MX a PEM line carries its own temperature, so it is both a PSU and a sensor.
        if cls.lower().startswith("power") or _PSU_ITEM.match(name):
            env["power_supplies"].append({"id": int(pm.group(1)) if pm else len(env["power_supplies"]),
                                          "name": name, "model": "", "status": status, "output_watts": None,
                                          "capacity_w": None, "comment": comment})
        elif celsius is None and (cls.lower().startswith("fan") or re.search(r"\bfan", name, re.I)):
            pct = re.search(r"(\d+)\s*%", comment)
            # 'Fan Tray 0 Fan 0' -> 'Tray 0 Fan 0': the page already prefixes FAN
            short = re.sub(r"^((?:FPC\s*\d+\s+)?)Fan\s+(?=Tray)", r"\1", name, flags=re.I)
            env["fans"].append({"id": short, "status": status, "actual_speed": int(pct.group(1)) if pct else None,
                                "speed_text": comment})

        if celsius is not None:
            env["sensors"].append({
                "id": len(env["sensors"]) + 1, "description": name, "temp": float(celsius),
                "setpoint": None, "alert_limit": None, "critical_limit": None,
                "status": status, "psu": int(pm.group(1)) if pm else None,
            })
            if env["ambient_temp"] is None and re.search(r"intake|inlet|ambient", name, re.I):
                env["ambient_temp"] = int(float(celsius))

    # the box's own verdict: chassis alarms. Temperature alarms -> temp_status, fan alarms -> cooling_status.
    temp_al, fan_al = [], []
    for a in find(p.get("alarms"), "alarm-detail"):
        desc = val(a, "alarm-description") or ""
        tag = f"{val(a, 'alarm-class') or 'Alarm'}: {desc}"
        if re.search(r"temp|hot|overheat|thermal", desc, re.I):
            temp_al.append(tag)
        elif re.search(r"\bfan|cooling|airflow", desc, re.I):
            fan_al.append(tag)
    reported = bool(env["sensors"] or env["fans"] or env["power_supplies"])
    if reported or "alarms" in p:
        env["temp_status"] = "; ".join(temp_al) if temp_al else "Ok"
        env["cooling_status"] = "; ".join(fan_al) if fan_al else "Ok"
    return env


def _passthrough_error(p: dict, key: str, built):
    """Keep a section's _error visible to the page (secErr) when nothing came back."""
    err = section_error(p, key)
    if err and not built:
        return {"_error": err}
    return built


def _env_or_error(p: dict):
    env = _environment(p)
    if not (env["sensors"] or env["fans"] or env["power_supplies"]):
        err = section_error(p, "environment")
        if err:
            return {"_error": err}
    return env


# ---------------------------------------------------------------------------------------------


def to_bridge(parsed: dict, meta: dict) -> dict:
    """Junos replies (parsed) -> the EOS-shaped payload the bridge page reads."""
    version, master = _version(parsed)
    statuses, counters = _interfaces(parsed)
    out = {
        "meta": meta,
        "version": _passthrough_error(parsed, "version", version if version.get("hostname") or version.get("modelName") else {}),
        "lldp": {"lldpNeighbors": _lldp(parsed)},
        "interfaces": _passthrough_error(parsed, "interfaces", {"interfaceStatuses": statuses} if statuses else {}),
        "counters": {"interfaces": counters},
        "ospf": _passthrough_error(parsed, "ospf", _ospf(parsed)),
        "bgp": _passthrough_error(parsed, "bgp", _bgp(parsed)),
        "routes": _passthrough_error(parsed, "routes", _routes(parsed)),
        "proc": _proc(master),
        "environment": _env_or_error(parsed),
        "logging": parsed.get("logging") if isinstance(parsed.get("logging"), list) else [],
    }
    if isinstance(parsed.get("logging"), dict) and parsed["logging"].get("_error"):
        out["logging"] = []
    lldp_err = section_error(parsed, "lldp")
    if lldp_err and not out["lldp"]["lldpNeighbors"]:
        out["lldp"]["_error"] = lldp_err
    return out
