"""Junos adapter against synthetic replies (tests/fixtures/junos-synthetic). Run: python -m pytest tests"""

import time
from pathlib import Path

import pytest

from netbridgeng.collectors.juniper.adapter import duration_seconds, speed_bps, to_bridge
from netbridgeng.collectors.juniper.collector import demo_payload, load_capture, parse_raw, parse_xml_output

FIX = Path(__file__).parent / "fixtures" / "junos-synthetic"


@pytest.fixture(scope="module")
def bridge():
    parsed = parse_raw(load_capture(FIX))
    return to_bridge(parsed, {"hostname": "t", "timestamp": time.time(), "platform": "juniper_junos"})


def test_version_through_multi_re_wrapper(bridge):
    v = bridge["version"]
    assert v["hostname"] == "qfx-lab-01"
    assert v["modelName"] == "QFX5120-48Y-8C"
    assert v["version"] == "21.4R3-S5.4"
    assert v["serialNumber"] == "WS0000000001"
    assert v["uptime"] == 3456789


def test_interfaces_physical_only(bridge):
    st = bridge["interfaces"]["interfaceStatuses"]
    assert set(st) == {"et-0/0/48", "et-0/0/49", "xe-0/0/1", "xe-0/0/2", "xe-0/0/3", "ae0", "em0"}
    assert st["et-0/0/48"]["bandwidth"] == 100_000_000_000
    assert st["xe-0/0/2"]["linkStatus"] == "notconnect"
    assert st["xe-0/0/3"]["linkStatus"] == "disabled"
    c = bridge["counters"]["interfaces"]["et-0/0/48"]
    assert c["outDiscards"] == 1200 and c["inOctets"] > 0


def test_lldp_ports_and_ifindex_fallback(bridge):
    n = {x["port"]: x for x in bridge["lldp"]["lldpNeighbors"]}
    assert n["et-0/0/48"]["neighborPort"] == "Ethernet1/1"
    assert n["et-0/0/49"]["neighborPort"] == "xe-0/1/0"      # ifIndex 537 replaced by the port description
    assert all(p in bridge["interfaces"]["interfaceStatuses"] for p in n)


def test_bgp(bridge):
    d = bridge["bgp"]["vrfs"]["default"]
    assert d["asn"] == "65020" and d["routerId"] == "10.255.0.11"
    p = d["peers"]
    assert p["203.0.113.1"]["peerState"] == "Established"
    assert p["203.0.113.1"]["prefixReceived"] == 949000
    assert p["2001:db8::1"]["prefixReceived"] == 210000      # inet6.0 peers count too
    assert p["10.10.0.2"]["peerState"] == "Active"
    assert abs((time.time() - p["203.0.113.1"]["upDownTime"]) - 1209845) < 5


def test_ospf_units_stripped(bridge):
    e = bridge["ospf"]["vrfs"]["default"]["instList"]["1"]["ospfNeighborEntries"]
    assert [x["interfaceName"] for x in e] == ["et-0/0/48", "et-0/0/49"]
    assert e[0]["adjacencyState"] == "full" and e[0]["drState"] == "P2P"


def test_routes_env_cpu_logging(bridge):
    r = bridge["routes"]["vrfs"]["default"]
    assert r["totalRoutes"] == 950321 and r["ospfCounts"] == {"ospfTotal": 230}
    env = bridge["environment"]
    assert len(env["sensors"]) == 5 and env["ambient_temp"] == 27
    assert all(s["setpoint"] is None for s in env["sensors"])
    assert [p["id"] for p in env["power_supplies"]] == [0, 1]
    assert len(env["fans"]) == 3 and env["fans"][2]["status"] == "Check"
    assert env["temp_status"] == "Ok" and env["cooling_status"].startswith("Minor:")
    assert bridge["proc"]["cpuInfo"]["%Cpu(s)"]["idle"] == 85
    assert bridge["logging"][1]["mnemonic"] == "BGP_IO_ERROR_CLOSE_SESSION"
    assert len(bridge["logging"]) == 5


def test_error_reply_and_empty():
    err = parse_xml_output('<rpc-reply><xnm:error xmlns:xnm="http://xml.juniper.net/xnm/1.1/xnm"><message>syntax error</message></xnm:error></rpc-reply>')
    assert err["_error"].startswith("junos: syntax error")
    b = to_bridge({"bgp": {"_error": "junos: bgp is not running"}}, {})
    assert b["bgp"] == {"_error": "junos: bgp is not running"}
    assert b["lldp"]["lldpNeighbors"] == []


@pytest.mark.parametrize("text,attr,secs", [
    ("2w0d 0:04:05", None, 1209845), ("2:33:54", None, 9234), ("12:34", None, 754),
    ("40 days, 30 minutes, 9 seconds", None, 3457809), ("12w3d", None, 7516800), ("x", "42", 42),
])
def test_durations(text, attr, secs):
    assert duration_seconds(text, attr) == secs


@pytest.mark.parametrize("text,bps", [("10Gbps", 10**10), ("1000mbps", 10**9), ("100G", 10**11), ("Auto", 0), ("Unlimited", 0)])
def test_speed(text, bps):
    assert speed_bps(text) == bps


MX_ENV = """<rpc-reply xmlns:junos="http://xml.juniper.net/junos/21.4R3/junos">
<environment-information xmlns="http://xml.juniper.net/junos/21.4R3/junos-chassis">
<environment-item><name>PEM 0</name><class>Power</class><status>Absent</status></environment-item>
<environment-item><name>PEM 1</name><status>OK</status><temperature junos:celsius="25">25 degrees C / 77 degrees F</temperature><comment>DC Input: OK</comment></environment-item>
<environment-item><name>PEM 4</name><status>OK</status><temperature junos:celsius="46">46 degrees C / 114 degrees F</temperature></environment-item>
<environment-item><name>CB 0 Exhaust Temp Sensor</name><class>Temp</class><status>OK</status><temperature junos:celsius="27">27 degrees C / 80 degrees F</temperature></environment-item>
<environment-item><name>Fan Tray 0 Fan 0</name><class>Fans</class><status>OK</status><comment>Spinning at normal speed</comment></environment-item>
<environment-item><name>Fan Tray 3 Fan 3</name><status>OK</status><comment>Spinning at normal speed</comment></environment-item>
</environment-information></rpc-reply>"""


def test_mx_pems_are_psus_and_sensors():
    env = to_bridge({"environment": parse_xml_output(MX_ENV)}, {})["environment"]
    assert [(p["id"], p["status"]) for p in env["power_supplies"]] == [(1, "OK"), (4, "OK")]   # absent PEM 0 skipped
    assert [s["description"] for s in env["sensors"]] == ["PEM 1", "PEM 4", "CB 0 Exhaust Temp Sensor"]
    assert [s["psu"] for s in env["sensors"]] == [1, 4, None]
    assert [f["id"] for f in env["fans"]] == ["Tray 0 Fan 0", "Tray 3 Fan 3"]


def test_demo_dataset_fills_every_section():
    b = demo_payload()
    assert b["version"]["modelName"] == "MX960"
    assert len(b["interfaces"]["interfaceStatuses"]) == 16 and len(b["counters"]["interfaces"]) == 16
    assert len(b["lldp"]["lldpNeighbors"]) == 9
    peers = b["bgp"]["vrfs"]["default"]["peers"]
    assert len(peers) == 12 and all(p["peerState"] == "Established" for p in peers.values())
    assert len(b["ospf"]["vrfs"]["default"]["instList"]["1"]["ospfNeighborEntries"]) == 4
    env = b["environment"]
    assert len(env["power_supplies"]) == 4 and len(env["fans"]) == 12 and env["temp_status"] == "Ok"
    assert b["proc"]["cpuInfo"]["%Cpu(s)"]["idle"] == 88 and len(b["logging"]) == 5
