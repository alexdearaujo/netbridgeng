"""
Writes the synthetic Junos demo dataset (netbridgeng/collectors/juniper/demo/) as raw '| display xml' replies.

A fictional MX edge router: two transits, an IX, two cores over OSPF and iBGP, aggregation and customer ports.
Documentation-range addresses (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) and ASNs
(64496-64511 public, 65000+ private) only. The server runs these through the real adapter for ?demo=junos.

  python tools/make_junos_demo.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "netbridgeng" / "collectors" / "juniper" / "demo"
NS = 'xmlns:junos="http://xml.juniper.net/junos/22.4R3/junos"'
HOST = "edge-01"


def reply(body: str) -> str:
    return f'<rpc-reply {NS}>\n{body}\n    <cli>\n        <banner>{{master}}</banner>\n    </cli>\n</rpc-reply>\n'


def leaf(tag, text, **attrs):
    a = "".join(f' junos:{k}="{v}"' for k, v in attrs.items())
    return f"<{tag}{a}>{text}</{tag}>"


# local port, speed, description, lldp (system, remote port) or None, base in / out octets
PORTS = [
    ("et-0/0/0", "100Gbps", "TRANSIT: Transit-A AS64500", ("tr-a-pe1.example.com", "et-3/0/1"), 4.1e15, 1.2e15),
    ("et-0/0/1", "100Gbps", "TRANSIT: Transit-B AS64501", None, 3.2e15, 0.9e15),
    ("et-0/0/2", "100Gbps", "CORE: core-01.dc1 et-0/0/4", ("core-01.dc1.example.net", "et-0/0/4"), 2.8e15, 5.1e15),
    ("et-0/0/3", "100Gbps", "CORE: core-02.dc1 et-0/0/4", ("core-02.dc1.example.net", "et-0/0/4"), 2.6e15, 4.9e15),
    ("et-1/0/0", "100Gbps", "IX: Example-IX peering LAN", ("ix-sw-03.example-ix.net", "Ethernet12/1"), 1.9e15, 0.7e15),
    ("et-1/0/1", "100Gbps", "AGG: agg-01.dc1 et-0/0/48", ("agg-01.dc1.example.net", "et-0/0/48"), 0.8e15, 1.4e15),
    ("xe-2/0/0", "10Gbps", "CUST: Customer-A AS64510", ("cust-a-rtr1", "ge-0/0/0"), 2.1e14, 0.6e14),
    ("xe-2/0/1", "10Gbps", "CUST: Customer-B AS64511", ("cust-b-rtr1", "xe-0/0/2"), 1.4e14, 0.5e14),
    ("xe-2/0/2", "10Gbps", "CUST: Customer-C (static)", None, 0.6e14, 0.2e14),
    ("xe-2/0/3", "10Gbps", "AGG: agg-02.dc1 xe-0/0/47", ("agg-02.dc1.example.net", "xe-0/0/47"), 0.9e14, 1.2e14),
    ("xe-2/0/4", "10Gbps", "MON: flow-collector-01", ("flow-collector-01.dc1.example.net", "eth2"), 0.1e14, 2.4e14),
    ("xe-2/0/5", "10Gbps", "spare", None, 0, 0),
    ("xe-2/0/6", "10Gbps", "", None, 0, 0),
    ("xe-2/0/7", "10Gbps", "reserved: Customer-D turn-up", None, 0, 0),
]
DOWN = {"xe-2/0/6"}
DISABLED = {"xe-2/0/5", "xe-2/0/7"}


def interfaces():
    rows = []
    for name, sp, desc, _l, ib, ob in PORTS + [("ae0", "200Gbps", "CORE: LAG to core-01/02", None, 5.4e15, 10.0e15),
                                             ("fxp0", "1000mbps", "MGMT: oob-sw-01", None, 2.1e10, 4.4e10)]:
        admin = "down" if name in DISABLED else "up"
        oper = "down" if name in DOWN | DISABLED else "up"
        rows.append(f"""    <physical-interface>
        {leaf('name', name)}
        {leaf('admin-status', admin, format='Enabled' if admin == 'up' else 'Disabled')}
        {leaf('oper-status', oper)}
        {leaf('description', desc) if desc else ''}
        {leaf('link-level-type', 'Ethernet')}
        {leaf('mtu', '9192')}
        {leaf('speed', sp)}
        {leaf('if-media-type', 'Copper' if name.startswith('fxp') else 'Fiber')}
        <traffic-statistics junos:style="verbose">
            {leaf('input-bytes', int(ib))}
            {leaf('input-bps', 0)}
            {leaf('output-bytes', int(ob))}
            {leaf('output-bps', 0)}
        </traffic-statistics>
        <input-error-list>{leaf('input-errors', 0)}{leaf('input-drops', 0)}{leaf('framing-errors', 0)}</input-error-list>
        <output-error-list>{leaf('carrier-transitions', 2)}{leaf('output-errors', 0)}{leaf('output-drops', 0)}</output-error-list>
        <logical-interface>{leaf('name', name + '.0')}</logical-interface>
    </physical-interface>""")
    for n in ["lo0", "irb", "pfe-0/0/0", "pfh-0/0/0", "gr-0/0/10", "lsi", "dsc", "tap", "mtun", "pip0"]:
        rows.append(f"    <physical-interface>{leaf('name', n)}{leaf('admin-status', 'up')}{leaf('oper-status', 'up')}{leaf('speed', 'Unlimited')}</physical-interface>")
    return reply('<interface-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-interface" junos:style="normal">\n'
                 + "\n".join(rows) + "\n</interface-information>")


def lldp():
    rows = []
    for name, _s, _d, l, _i, _o in PORTS:
        if not l:
            continue
        rows.append(f"""    <lldp-neighbor-information>
        {leaf('lldp-local-port-id', name)}
        {leaf('lldp-local-parent-interface-name', 'ae0' if name in ('et-0/0/2', 'et-0/0/3') else '-')}
        {leaf('lldp-remote-chassis-id-subtype', 'Mac address')}
        {leaf('lldp-remote-chassis-id', '02:00:00:00:%02x:01' % (len(rows) + 1))}
        {leaf('lldp-remote-port-id-subtype', 'Interface name')}
        {leaf('lldp-remote-port-id', l[1])}
        {leaf('lldp-remote-system-name', l[0])}
    </lldp-neighbor-information>""")
    return reply('<lldp-neighbors-information junos:style="brief">\n' + "\n".join(rows) + "\n</lldp-neighbors-information>")


# peer, AS, description, state, elapsed seconds, [(rib, received, accepted)]
PEERS = [
    ("203.0.113.1", 64500, "TRANSIT-A", "Established", 41 * 86400 + 3600, [("inet.0", 951233, 951230)]),
    ("2001:db8:100::1", 64500, "TRANSIT-A-V6", "Established", 41 * 86400 + 3500, [("inet6.0", 212045, 212040)]),
    ("198.51.100.9", 64501, "TRANSIT-B", "Established", 17 * 86400, [("inet.0", 950870, 950862)]),
    ("2001:db8:200::9", 64501, "TRANSIT-B-V6", "Established", 17 * 86400, [("inet6.0", 211980, 211979)]),
    ("192.0.2.21", 64505, "IX: Example-CDN", "Established", 6 * 86400, [("inet.0", 3120, 3120)]),
    ("192.0.2.22", 64506, "IX: Example-Cloud", "Established", 29 * 86400, [("inet.0", 8412, 8410)]),
    ("192.0.2.23", 64507, "IX: Example-ISP", "Established", 2 * 86400, [("inet.0", 645, 645)]),
    ("192.0.2.1", 64508, "IX: route-server-1", "Established", 88 * 86400, [("inet.0", 61230, 61101)]),
    ("10.255.0.1", 65020, "iBGP core-01", "Established", 120 * 86400, [("inet.0", 1880, 1880)]),
    ("10.255.0.2", 65020, "iBGP core-02", "Established", 120 * 86400, [("inet.0", 1880, 1880)]),
    ("198.51.100.30", 64510, "CUST: Customer-A", "Established", 9 * 86400, [("inet.0", 12, 12)]),
    ("198.51.100.34", 64511, "CUST: Customer-B", "Established", 52 * 86400, [("inet.0", 3, 3)]),
]


def dur(s):
    w, s = divmod(s, 604800)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{w}w{d}d {h}:{m:02d}:{s:02d}" if w or d else f"{h}:{m:02d}:{s:02d}"


def bgp():
    rows = []
    for ip, asn, desc, st, el, ribs in PEERS:
        rib = "".join(f"<bgp-rib junos:style=\"terse\">{leaf('name', r)}{leaf('active-prefix-count', int(a * .48))}"
                      f"{leaf('received-prefix-count', rx)}{leaf('accepted-prefix-count', a)}{leaf('suppressed-prefix-count', 0)}</bgp-rib>"
                      for r, rx, a in ribs)
        rows.append(f"""    <bgp-peer junos:style="terse">
        {leaf('peer-address', ip)}
        {leaf('peer-as', asn)}
        {leaf('input-messages', 1200000 if ribs[0][1] > 1e5 else 90000)}
        {leaf('output-messages', 40000)}
        {leaf('route-queue-count', 0)}
        {leaf('flap-count', 1)}
        {leaf('elapsed-time', dur(el), seconds=el)}
        {leaf('description', desc)}
        {leaf('peer-state', st, format='Establ')}
        {rib}
    </bgp-peer>""")
    return reply('<bgp-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-routing">\n'
                 f"    {leaf('group-count', 5)}{leaf('peer-count', len(PEERS))}{leaf('down-peer-count', 0)}\n"
                 + "\n".join(rows) + "\n</bgp-information>")


def ospf():
    rows = []
    for addr, ifn, rid in [("10.0.0.1", "et-0/0/2.0", "10.255.0.1"), ("10.0.0.3", "et-0/0/3.0", "10.255.0.2"),
                           ("10.0.0.9", "et-1/0/1.0", "10.255.0.21"), ("10.0.0.13", "xe-2/0/3.0", "10.255.0.22")]:
        rows.append(f"""    <ospf-neighbor>
        {leaf('neighbor-address', addr)}{leaf('interface-name', ifn)}{leaf('ospf-neighbor-state', 'Full')}
        {leaf('neighbor-id', rid)}{leaf('neighbor-priority', 128)}{leaf('activity-timer', 33)}
        {leaf('ospf-area', '0.0.0.0')}{leaf('options', '0x52')}{leaf('dr-address', '0.0.0.0')}{leaf('bdr-address', '0.0.0.0')}
        {leaf('neighbor-up-time', '17w2d 04:11:09', seconds=10469469)}{leaf('neighbor-adjacency-time', '17w2d 04:11:09', seconds=10469469)}
    </ospf-neighbor>""")
    return reply('<ospf-neighbor-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-routing">\n'
                 + "\n".join(rows) + "\n</ospf-neighbor-information>")


def environment():
    it = []

    def add(name, cls, status, celsius=None, comment=None):
        t = f'<temperature junos:celsius="{celsius}">{celsius} degrees C / {round(celsius * 9 / 5 + 32)} degrees F</temperature>' if celsius is not None else ""
        it.append(f"    <environment-item>{leaf('name', name)}{leaf('class', cls) if cls else ''}{leaf('status', status)}{t}"
                  f"{leaf('comment', comment) if comment else ''}</environment-item>")

    for i, t in enumerate([31, 34, 29, 33]):
        add(f"PEM {i}", "Power" if i == 0 else None, "OK", t, "DC Input: OK, DC Output: OK")
    for i, (n, t) in enumerate([("Routing Engine 0", 36), ("Routing Engine 0 CPU", 47), ("Routing Engine 1", 33),
                                ("CB 0 Intake Temp Sensor", 24), ("CB 0 Exhaust Temp Sensor", 31),
                                ("CB 1 Intake Temp Sensor", 25), ("CB 1 Exhaust Temp Sensor", 30),
                                ("FPC 0 Intake Temp Sensor", 26), ("FPC 0 Exhaust-A Temp Sensor", 48), ("FPC 0 Exhaust-B Temp Sensor", 41),
                                ("FPC 0 XL 0 TSen", 58), ("FPC 0 XL 0 Chip", 66), ("FPC 0 XM 0 Chip", 62),
                                ("FPC 1 Intake Temp Sensor", 25), ("FPC 1 Exhaust-A Temp Sensor", 46), ("FPC 1 XL 0 Chip", 64),
                                ("FPC 2 Intake Temp Sensor", 24), ("FPC 2 Exhaust-A Temp Sensor", 39), ("FPC 2 LU 0 Chip", 54)]):
        add(n, "Temp" if i == 0 else None, "OK", t)
    for tray in range(3):
        for f in range(4):
            add(f"Fan Tray {tray} Fan {f}", "Fans" if tray == f == 0 else None, "OK", None, "Spinning at normal speed")
    add("Fan Tray 3 Fan 0", None, "Absent")     # empty slot: skipped by the adapter
    return reply('<environment-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-chassis">\n'
                 + "\n".join(it) + "\n</environment-information>")


FILES = {
    "version": reply(f"""<software-information>
    {leaf('host-name', HOST)}
    {leaf('product-model', 'mx960')}
    {leaf('product-name', 'mx960')}
    {leaf('junos-version', '22.4R3-S2.11')}
</software-information>"""),
    "hardware": reply("""<chassis-inventory xmlns="http://xml.juniper.net/junos/22.4R3/junos-chassis">
    <chassis junos:style="inventory"><name>Chassis</name><serial-number>JN0000000DEMO</serial-number><description>MX960</description></chassis>
</chassis-inventory>"""),
    "routing_engine": reply(f"""<route-engine-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-chassis">
    <route-engine>
        {leaf('slot', 0)}{leaf('mastership-state', 'master')}{leaf('mastership-priority', 'Master (default)')}
        {leaf('memory-dram-size', '65536 MB')}{leaf('memory-buffer-utilization', 31)}
        {leaf('cpu-user', 7)}{leaf('cpu-background', 0)}{leaf('cpu-system', 4)}{leaf('cpu-interrupt', 1)}{leaf('cpu-idle', 88)}
        {leaf('model', 'RE-S-X6-64G')}
        {leaf('up-time', '187 days, 4 hours, 12 minutes, 51 seconds', seconds=16172971)}
    </route-engine>
    <route-engine>
        {leaf('slot', 1)}{leaf('mastership-state', 'backup')}{leaf('cpu-idle', 99)}{leaf('memory-dram-size', '65536 MB')}
        {leaf('up-time', '187 days, 4 hours, 9 minutes, 2 seconds', seconds=16172742)}
    </route-engine>
</route-engine-information>"""),
    "environment": environment(),
    "alarms": reply("""<alarm-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-alarm">
    <alarm-summary><no-active-alarms/></alarm-summary>
</alarm-information>"""),
    "bgp": bgp(),
    "routing_options": reply("""<configuration junos:commit-seconds="1763290000" junos:commit-user="netops">
    <routing-options>
        <router-id>10.255.0.11</router-id>
        <autonomous-system><as-number>65020</as-number></autonomous-system>
    </routing-options>
</configuration>"""),
    "ospf": ospf(),
    "lldp": lldp(),
    "routes": reply("""<route-summary-information xmlns="http://xml.juniper.net/junos/22.4R3/junos-routing">
    <route-table>
        <table-name>inet.0</table-name><destination-count>951803</destination-count><total-route-count>2876402</total-route-count>
        <active-route-count>951803</active-route-count><holddown-route-count>0</holddown-route-count><hidden-route-count>41</hidden-route-count>
        <protocols><protocol-name>Direct</protocol-name><protocol-route-count>22</protocol-route-count><active-route-count>22</active-route-count></protocols>
        <protocols><protocol-name>Local</protocol-name><protocol-route-count>22</protocol-route-count><active-route-count>22</active-route-count></protocols>
        <protocols><protocol-name>OSPF</protocol-name><protocol-route-count>318</protocol-route-count><active-route-count>296</active-route-count></protocols>
        <protocols><protocol-name>Static</protocol-name><protocol-route-count>9</protocol-route-count><active-route-count>9</active-route-count></protocols>
        <protocols><protocol-name>BGP</protocol-name><protocol-route-count>2876031</protocol-route-count><active-route-count>951454</active-route-count></protocols>
    </route-table>
    <route-table><table-name>inet6.0</table-name><destination-count>212311</destination-count><total-route-count>424102</total-route-count><active-route-count>212311</active-route-count></route-table>
</route-summary-information>"""),
    "interfaces": interfaces(),
}

LOG = """
Nov 16 06:12:40  edge-01 mgd[61022]: UI_LOGIN_EVENT: User 'netops' login, class 'j-super-user' [61022], ssh-connection '192.0.2.200 52218 192.0.2.11 22', client-mode 'cli'
Nov 16 06:13:02  edge-01 mgd[61022]: UI_CMDLINE_READ_LINE: User 'netops', command 'show bgp summary '
Nov 16 06:40:11  edge-01 rpd[2210]: RPD_BGP_NEIGHBOR_STATE_CHANGED: BGP peer 192.0.2.23 (External AS 64507) changed state from OpenConfirm to Established (event RecvKeepAlive) (instance master)
Nov 16 07:05:19  edge-01 chassisd[1999]: CHASSISD_FRU_ONLINE_TIMEOUT: Fan Tray 3 not present
Nov 16 07:30:00  edge-01 sshd[71100]: Accepted publickey for netops from 192.0.2.200 port 52301 ssh2: RSA SHA256:demo
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for k, v in FILES.items():
        (OUT / f"{k}.xml").write_text(v)
    (OUT / "logging.txt").write_text(LOG.lstrip("\n"))
    print(f"wrote {len(FILES) + 1} files to {OUT}")


if __name__ == "__main__":
    main()
