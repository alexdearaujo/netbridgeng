"""
Juniper Junos data collector using Netmiko.

Runs show commands with '| display xml' (works on old Junos that lacks '| display json'),
converts each reply into the dict shape '| display json' would give, then hands the set to
adapter.to_bridge(), which maps it onto the EOS-shaped contract the bridge page reads.
The raw (pre-adapter) set from the last poll is kept on the collector for debugging.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

from .adapter import to_bridge

logger = logging.getLogger("collector.juniper")

PLATFORM = "juniper_junos"

# key -> command. All XML, paged off with '| no-more'.
# interfaces: 'extensive' is the lightest view that carries both octets and drop counters;
# it is also the heaviest command here on a box with many logical units (override in config.yaml).
COMMANDS = {
    "version":         "show version | display xml | no-more",
    "hardware":        "show chassis hardware | display xml | no-more",
    "routing_engine":  "show chassis routing-engine | display xml | no-more",
    "environment":     "show chassis environment | display xml | no-more",
    "alarms":          "show chassis alarms | display xml | no-more",
    "bgp":             "show bgp summary | display xml | no-more",
    "routing_options": "show configuration routing-options | display xml | no-more",
    "ospf":            "show ospf neighbor detail | display xml | no-more",
    "lldp":            "show lldp neighbors | display xml | no-more",
    "routes":          "show route summary | display xml | no-more",
    "interfaces":      "show interfaces extensive | display xml | no-more",
}

TEXT_COMMANDS = {
    "logging": "show log messages | last 50 | no-more",
}

SLOW = {"interfaces": 120, "environment": 90, "hardware": 90}


# ---------------------------------------------------------------------------------------------
# XML -> Junos-JSON-shaped dict
# ---------------------------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag[tag.index("}") + 1:] if tag.startswith("{") else tag


def xml_to_juniper_dict(element) -> list:
    """
    Convert an element to the structure Junos '| display json' produces:
      leaf   -> [{"data": "text", "attributes": {...}}]
      branch -> [{child_tag: [...], ...}]
    Repeated sibling tags are collected into one list. XML attributes keep a 'junos:' prefix
    (junos:seconds, junos:celsius, ...).
    """
    children = list(element)
    if not children:
        entry = {"data": (element.text or "").strip()}
        if element.attrib:
            attrs = {}
            for k, v in element.attrib.items():
                if k.startswith("{"):
                    attrs[f"junos:{_local(k)}"] = v
                else:
                    attrs[k] = v
            entry["attributes"] = attrs
        return [entry]

    result: dict[str, list] = {}
    for child in children:
        result.setdefault(_local(child.tag), []).extend(xml_to_juniper_dict(child))
    return [result]


_XMLNS = re.compile(r'\sxmlns(?::[\w-]+)?\s*=\s*"[^"]*"')


def parse_xml_output(raw: str) -> dict:
    """Parse one command's '| display xml' reply. Returns {top_tag: [...]} or {'_error': ...}."""
    raw = (raw or "").strip()
    start = raw.find("<rpc-reply")
    if start < 0:
        start = raw.find("<?xml")
    if start < 0:
        start = raw.find("<")
    if start < 0:
        return {"_raw": raw[:500], "_error": "no_xml_found"}
    raw = raw[start:]
    end = raw.rfind("</rpc-reply>")
    if end >= 0:
        raw = raw[: end + len("</rpc-reply>")]

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        try:
            root = ET.fromstring(_XMLNS.sub("", raw))
        except ET.ParseError as e:
            return {"_raw": raw[:500], "_error": f"xml_parse_failed: {e}"}

    if _local(root.tag) != "rpc-reply":
        return {_local(root.tag): xml_to_juniper_dict(root)}

    result: dict[str, Any] = {}
    for child in root:
        tag = _local(child.tag)
        if tag == "cli":            # <cli><banner>{master:0}</banner></cli> trailer
            continue
        if tag == "xnm:error" or tag == "error":
            msg = child.findtext(".//message") or (child.text or "").strip()
            return {"_error": f"junos: {msg.strip() or 'error'}"}
        result.setdefault(tag, []).extend(xml_to_juniper_dict(child))
    if not result:
        # e.g. 'show bgp summary' with BGP not configured: an empty reply or only a <output> text
        return {}
    return result


_SYSLOG = re.compile(
    r"^(?P<ts>\w{3}\s+\d+\s+[\d:]+(?:\.\d+)?)\s+(?P<host>\S+)\s+(?P<src>[^:\s]+?)(?:\[\d+\])?:\s+(?P<msg>.+)$"
)
_MNEMONIC = re.compile(r"^([A-Z][A-Z0-9_]{3,}):\s+(.*)$")


def parse_logging_text(raw: str) -> list[dict[str, Any]]:
    """
    'show log messages' lines -> bridge log entries. Junos does not print the severity in the
    default messages file format, so severity is 6 unless the line is in structured form.
    The UPPER_CASE tag at the start of the message (UI_CMDLINE_READ_LINE, SNMP_TRAP_LINK_DOWN)
    becomes the mnemonic.
    """
    out = []
    for line in raw.splitlines():
        m = _SYSLOG.match(line.strip())
        if not m:
            continue
        msg = m.group("msg").strip()
        mnem = ""
        mm = _MNEMONIC.match(msg)
        if mm:
            mnem, msg = mm.group(1), mm.group(2)
        out.append({
            "timestamp": m.group("ts"),
            "host": m.group("host"),
            "source": m.group("src"),
            "facility": "",
            "severity": 6,
            "mnemonic": mnem,
            "message": msg,
        })
    return out


def parse_raw(raw_by_key: dict[str, str]) -> dict[str, Any]:
    """Raw command text by key -> parsed dicts (what collect() feeds to the adapter)."""
    parsed: dict[str, Any] = {}
    for key, text in raw_by_key.items():
        if key == "logging":
            parsed[key] = parse_logging_text(text)
        else:
            parsed[key] = parse_xml_output(text)
    return parsed


def load_capture(d: Path) -> dict[str, str]:
    """Raw replies saved by 'capture' (<key>.xml, logging.txt) -> raw text by key."""
    raw = {}
    for key in list(COMMANDS) + list(TEXT_COMMANDS):
        f = Path(d) / (f"{key}.txt" if key in TEXT_COMMANDS else f"{key}.xml")
        if f.is_file():
            raw[key] = f.read_text()
    return raw


DEMO_DIR = Path(__file__).parent / "demo"


def demo_payload() -> dict[str, Any]:
    """The synthetic MX edge router (demo/, written by tools/make_junos_demo.py) run through the real adapter."""
    return to_bridge(parse_raw(load_capture(DEMO_DIR)), {
        "hostname": "edge-01.dc1.example.net", "poll_count": 0, "poll_time": 0, "error": None,
        "timestamp": time.time(), "platform": PLATFORM, "demo": True,
    })


# ---------------------------------------------------------------------------------------------
# collector
# ---------------------------------------------------------------------------------------------

class JuniperCollector:
    """Collects operational state from a Juniper Junos device via Netmiko."""

    platform = PLATFORM

    def __init__(self, device_config: dict):
        self.device_params = {
            "device_type": PLATFORM,
            "host": device_config["host"],
            "username": device_config["username"],
            "use_keys": device_config.get("use_keys", True),
            "allow_agent": False,
            "timeout": device_config.get("timeout", 45),
            "session_timeout": device_config.get("session_timeout", 60),
            "conn_timeout": device_config.get("timeout", 45),
        }
        if device_config.get("port"):
            self.device_params["port"] = int(device_config["port"])
        if device_config.get("key_file"):
            self.device_params["key_file"] = str(Path(device_config["key_file"]).expanduser())
        if device_config.get("password"):
            self.device_params["password"] = device_config["password"]
            self.device_params["use_keys"] = False
        if device_config.get("legacy_ssh", False):
            self.device_params["disabled_algorithms"] = {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]}
            logger.info(f"Legacy SSH mode enabled for {device_config['host']}")

        self.commands = dict(COMMANDS)
        override = (device_config.get("juniper") or {}).get("interfaces_command")
        if override:
            self.commands["interfaces"] = override

        self.hostname = device_config["host"]
        self._conn = None
        self._prompt_re: str | None = None
        self._last_data: dict[str, Any] | None = None
        self._last_raw: dict[str, str] = {}
        self._last_error: str | None = None
        self._last_collect_time: float = 0
        self._collect_count: int = 0

    def _ensure_connected(self):
        if self._conn is not None:
            try:
                if self._conn.is_alive():
                    return
            except Exception:
                pass
            try:
                self._conn.disconnect()
            except Exception:
                pass
            self._conn = None
            self._prompt_re = None
            logger.info(f"Session to {self.hostname} dropped, reconnecting")

        self._conn = ConnectHandler(**self.device_params)
        # VC / dual-RE boxes print '{master:0}' on the line above the prompt: match the last line only
        prompt = self._conn.find_prompt().strip().splitlines()[-1].strip()
        self._prompt_re = re.escape(prompt.rstrip(">#%")) + r"[>#%]\s*$"
        logger.info(f"Persistent session to {self.hostname}, prompt: '{prompt}'")
        try:
            self._conn.send_command("set cli screen-length 0", expect_string=self._prompt_re, read_timeout=10)
            self._conn.send_command("set cli screen-width 0", expect_string=self._prompt_re, read_timeout=10)
        except Exception as e:
            logger.warning(f"Failed to disable pagination: {e}")

    def test_connect(self):
        self._ensure_connected()

    def disconnect(self):
        if self._conn:
            try:
                self._conn.disconnect()
            except Exception:
                pass
            self._conn = None
            self._prompt_re = None

    def _send(self, cmd: str, read_timeout: int = 45) -> str:
        kwargs = {"command_string": cmd, "read_timeout": read_timeout}
        if self._prompt_re:
            kwargs["expect_string"] = self._prompt_re
        return self._conn.send_command(**kwargs)

    def collect_raw(self, on_progress=None) -> dict[str, str]:
        """Run every command once and return the raw text by key (errors as '_error:<text>')."""
        t0 = time.time()
        raw: dict[str, str] = {}
        plan = list(self.commands.items()) + list(TEXT_COMMANDS.items())
        total = len(plan)
        for idx, (key, cmd) in enumerate(plan):
            if on_progress:
                try:
                    on_progress(key, idx, total, time.time() - t0, "start")
                except Exception:
                    pass
            try:
                raw[key] = self._send(cmd, read_timeout=SLOW.get(key, 45))
            except Exception as e:
                logger.warning(f"Command failed '{cmd}': {e}")
                raw[key] = f"_error:{e}"
                if "socket" in str(e).lower() or "closed" in str(e).lower():
                    self._conn = None
                    break
            if on_progress:
                try:
                    on_progress(key, idx + 1, total, time.time() - t0, "done")
                except Exception:
                    pass
        return raw

    def collect(self, on_progress=None) -> dict[str, Any]:
        t0 = time.time()
        self._collect_count += 1
        logger.info(f"Poll #{self._collect_count} starting for {self.hostname}")
        try:
            self._ensure_connected()
        except NetmikoAuthenticationException as e:
            self._last_error = f"Auth failed: {e}"
            logger.error(self._last_error)
            return self._stale_or_error()
        except NetmikoTimeoutException as e:
            self._last_error = f"Timeout: {e}"
            logger.error(self._last_error)
            return self._stale_or_error()
        except Exception as e:
            self._last_error = f"Connection failed: {e}"
            logger.error(self._last_error)
            return self._stale_or_error()

        try:
            raw = self.collect_raw(on_progress)
        except Exception as e:
            logger.error(f"Unexpected error during collection: {e}")
            self._conn = None
            raw = {}

        self._last_raw = raw
        parsed = {}
        for key, text in raw.items():
            if text.startswith("_error:"):
                parsed[key] = {"_error": text[len("_error:"):]}
            elif key == "logging":
                parsed[key] = parse_logging_text(text)
            else:
                parsed[key] = parse_xml_output(text)
                if "_error" in parsed[key]:
                    logger.warning(f"XML issue for '{key}': {parsed[key]['_error']}")

        elapsed = time.time() - t0
        data = to_bridge(parsed, {
            "hostname": self.hostname,
            "poll_count": self._collect_count,
            "poll_time": round(elapsed, 2),
            "error": None,
            "timestamp": time.time(),
            "platform": PLATFORM,
        })
        self._last_data = data
        self._last_error = None
        self._last_collect_time = time.time()
        logger.info(f"Poll #{self._collect_count} complete in {elapsed:.1f}s")
        return data

    def _stale_or_error(self) -> dict[str, Any]:
        if self._last_data:
            stale = dict(self._last_data)
            stale["meta"] = dict(stale.get("meta", {}))
            stale["meta"].update(error=self._last_error, stale=True, timestamp=time.time())
            return stale
        return {"meta": {
            "hostname": self.hostname, "poll_count": self._collect_count, "poll_time": 0,
            "error": self._last_error, "stale": False, "timestamp": time.time(), "platform": PLATFORM,
        }}
