"""
Capture and replay for the Junos adapter.

  python -m netbridgeng.collectors.juniper capture --host edge1-01.fra1 --user scott --out cap/edge1-01
  python -m netbridgeng.collectors.juniper adapt cap/edge1-01

capture: runs every collector command once and writes the raw replies (<key>.xml / logging.txt),
         then the adapted payload (bridge.json) and a coverage report.
adapt:   re-runs the adapter offline against a capture directory: the loop for fixing the adapter
         without touching the device again.
"""

import argparse
import getpass
import json
import sys
import time
from pathlib import Path

from .adapter import to_bridge
from .collector import COMMANDS, TEXT_COMMANDS, JuniperCollector, load_capture, parse_raw


def coverage(b: dict) -> list[str]:
    st = b.get("interfaces", {}).get("interfaceStatuses", {})
    peers = b.get("bgp", {}).get("vrfs", {}).get("default", {}).get("peers", {})
    ospf = [e for i in b.get("ospf", {}).get("vrfs", {}).get("default", {}).get("instList", {}).values()
            for e in i.get("ospfNeighborEntries", [])]
    env = b.get("environment", {})
    v = b.get("version", {})
    rows = [
        ("version", f"{v.get('hostname') or '-'} {v.get('modelName') or '-'} {v.get('version') or '-'} up {v.get('uptime') or 0}s"),
        ("interfaces", f"{len(st)} physical, {sum(1 for x in st.values() if x['linkStatus'] == 'connected')} connected, "
                       f"{sum(1 for x in st.values() if x['bandwidth'])} with speed"),
        ("counters", f"{len(b.get('counters', {}).get('interfaces', {}))} ports with octets"),
        ("lldp", f"{len(b.get('lldp', {}).get('lldpNeighbors', []))} neighbors"),
        ("bgp", f"{len(peers)} peers, {sum(1 for p in peers.values() if p['peerState'] == 'Established')} established, "
                f"AS {b.get('bgp', {}).get('vrfs', {}).get('default', {}).get('asn') or '-'}"),
        ("ospf", f"{len(ospf)} neighbors"),
        ("routes", f"{b.get('routes', {}).get('vrfs', {}).get('default', {}).get('totalRoutes', '-')} in inet.0"),
        ("cpu", f"idle {b.get('proc', {}).get('cpuInfo', {}).get('%Cpu(s)', {}).get('idle', '-')}"),
        ("environment", f"{len(env.get('sensors', []))} sensors, {len(env.get('fans', []))} fans, "
                        f"{len(env.get('power_supplies', []))} PSUs, temp {env.get('temp_status')}"),
        ("logging", f"{len(b.get('logging', []))} lines"),
    ]
    out = []
    for k, line in rows:
        err = b.get(k, {}).get("_error") if isinstance(b.get(k), dict) else None
        out.append(f"  {k:<12} {('ERROR ' + err) if err else line}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m netbridgeng.collectors.juniper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="collect once from a device and save raw replies")
    c.add_argument("--host", required=True)
    c.add_argument("--user", required=True)
    c.add_argument("--key", default="~/.ssh/id_rsa", help="private key (default ~/.ssh/id_rsa)")
    c.add_argument("--password", action="store_true", help="prompt for a password instead of key auth")
    c.add_argument("--legacy-ssh", action="store_true")
    c.add_argument("--out", required=True)
    a = sub.add_parser("adapt", help="re-run the adapter on a capture directory")
    a.add_argument("dir")
    args = ap.parse_args(argv)

    if args.cmd == "capture":
        cfg = {"host": args.host, "username": args.user, "legacy_ssh": args.legacy_ssh}
        if args.password:
            cfg["password"] = getpass.getpass(f"{args.user}@{args.host} password: ")
        else:
            cfg.update(use_keys=True, key_file=args.key)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        col = JuniperCollector(cfg)
        col.test_connect()
        t0 = time.time()

        def prog(key, idx, total, el, phase="done"):
            if phase == "start":
                print(f"  [{idx + 1}/{total}] {key} ...", end="", flush=True)
            else:
                print(f" {el:.1f}s", flush=True)

        raw = col.collect_raw(on_progress=prog)
        col.disconnect()
        for key, text in raw.items():
            (out / (f"{key}.txt" if key in TEXT_COMMANDS else f"{key}.xml")).write_text(text)
        print(f"raw replies written to {out}/ in {time.time() - t0:.1f}s")
        src = out
    else:
        src = Path(args.dir)
        raw = load_capture(src)
        if not raw:
            sys.exit(f"no capture files in {src}")

    parsed = {}
    for key, text in raw.items():
        parsed[key] = {"_error": text[7:]} if text.startswith("_error:") else parse_raw({key: text})[key]
    b = to_bridge(parsed, {"hostname": "capture", "poll_count": 1, "poll_time": 0, "error": None,
                           "timestamp": time.time(), "platform": "juniper_junos"})
    (src / "bridge.json").write_text(json.dumps(b, indent=2, default=str))
    print(f"adapted payload: {src / 'bridge.json'}")
    print("\n".join(coverage(b)))


if __name__ == "__main__":
    main()
