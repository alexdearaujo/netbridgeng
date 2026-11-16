# netbridgeng

**Network devices already know a great deal. Their interfaces don't show it.**

![The bridge: LLDP and OSPF radar](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/01-lldp-ospf-radar.png)

> **Status: proof of concept (alpha).** Read-only telemetry plus the device's own CLI, one device at a time. The web page has no login and the server opens SSH sessions on request, so it listens on `127.0.0.1` by default: keep it there unless something in front of it authenticates. See [Security](#security).

```bash
pip install netbridgeng
netbridgeng
```

Then open <http://127.0.0.1:8470/?demo> for the demo, or <http://127.0.0.1:8470/> to connect to a switch. Everything it needs is bundled: it runs with no internet access.

## Why this exists

A modern switch carries a remarkable amount of live, structured information: every neighbor it can see, the traffic on every port, dozens of temperature sensors with their own limits, the state and history of every routing session. Most of it is one `show` command away, and on many platforms it already comes back as clean JSON.

What it comes back *to* is a CLI built for the 1990s, or a web UI that was an afterthought. The information is there. The interface is the bottleneck.

For most of networking's history that was simply the deal: the vendor shipped the box and the vendor decided how you got to see it. That has changed. The data is structured, the browser can draw anything, and building an interface is no longer a project measured in quarters. **As customers, we can now decide what our own equipment looks like.**

netbridgeng is a proof of concept with that point to make. It connects to one switch over SSH, runs ordinary `show` commands, and renders the answers as a ship's bridge: a 3D radar of the device's neighbors, a skyline of port utilization over time, a see-through chassis with its sensors and airflow, a shield of BGP sessions, a map of OSPF adjacencies, and the device's own CLI in a console of its own.

It is not trying to be practical. It is not a monitoring system, it keeps no history beyond the open page, and nobody needs a radar to read `show lldp neighbors`. Its job is to explore what is possible, and to make the case that the distance between the data a device holds and the way we are shown it is a choice, not a law.

Arista EOS is the example because `| json` makes it easy. The idea is not Arista's: see [Not just Arista](#not-just-arista).

## What it shows

All screenshots are from the built-in demo mode (`?demo`): a fictional spine in a spine/leaf fabric with sample data that moves, drops a leaf link and flaps a BGP session now and then.

| | |
|---|---|
| ![LLDP neighbor lost](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/02-lldp-neighbor-lost.png) | **LLDP / OSPF radar.** Every LLDP neighbor is a contact. Bearing is the local port's order on the chassis, range is the neighbor's tier (border and spine close in, leaves further out), height separates tiers above and below. Traffic streams along each link at a density set by load; a ring marks an OSPF FULL adjacency. A neighbor that ages out leaves a fading red ghost. |
| ![Interface utilization](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/03-interface-utilization.png) | **Interface utilization.** The front panel as a skyline: in and out columns per port, height on a labelled square-root scale so 1% links still show beside a busy 100G uplink, heat from amber (over 50%) to red (over 80%). The last 40 polls recede behind the front row, so a burst and a sustained climb look different. Discards throw red sparks. |
| ![Environment](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/04-environment.png) | **Environment.** The chassis as a translucent hull. Each sensor is a heat point with a gauge whose rings mark the device's own setpoint, alert and critical limits. Fans spin at their reported speed, PSUs glow with their draw, and airflow particles cross the box in the reported direction, warming as they pass hot sensors. |
| ![Environment detail](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/04b-environment-detail.png) | **Environment detail.** Every sensor grouped and readable: temperature, a bar marked with all three limits, headroom, and a sparkline of the session so far. Fans and PSUs below. |
| ![BGP](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/05-bgp.png) | **BGP.** The router inside a shield, one segment per peer. iBGP peers orbit close, eBGP further out. Columns are received prefixes (log scale), arcs are session uptime, particles on each beam are UPDATE traffic from the message counters. |
| ![BGP session down](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/06-bgp-session-down.png) | **A session drops.** The peer falls out to the NOT ESTABLISHED ring, its beam breaks, its shield segment flickers red, a shockwave crosses the shield and the whole bridge goes to CRITICAL with the reason in the header. |
| ![OSPF](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/07b-ospf.png) | **OSPF.** Adjacencies on one ring per area. The conduit's color is the adjacency state, the sleeve is BFD, a pulse runs while it holds. Beads count state changes (red ones happened since the page opened); retransmissions that rose since the last poll throw amber sparks. The column over the router stacks its OSPF routes by type. |
| ![OSPF adjacency lost](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/07-ospf-adjacency-lost.png) | **An adjacency is lost** when the leaf link drops: red, fading, and counted in the header. |
| ![SSH console](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/08-ssh-console-demo.png) | **The device's own CLI**, in a console that sits over the bridge rather than in it: a solid, extruded slab, draggable and resizable, on the same session as the telemetry. In demo mode a small shell answers a few `show` commands from the sample data. |
| ![Connect](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/00-connect.png) | **Connect** straight to a device: SSH key on the server, an uploaded key, or a password. The server tests SSH before it creates the session. |
| ![Phone](https://raw.githubusercontent.com/scottpeterman/netbridgeng/main/screenshots/09-phone.png) | **On a phone** the stations stack under the main screen. |

Side stations (BGP peers, environment, interfaces, syslog) stay in view around the main screen, and tapping one switches the main screen to its 3D view. The header carries one status, **HEALTHY / DEGRADED / CRITICAL**, with the reason beside it.

### Every visual is a value the device already reports

| What you see | Where it comes from |
|---|---|
| Radar contacts, bearings, names | `show lldp neighbors \| json` and the port list from `show interfaces status \| json` |
| Traffic on links, utilization skyline, discard sparks | `show interfaces counters \| json`, differenced between polls, against each port's `bandwidth` |
| Sensor heat, gauge rings, headroom | `show system environment all`: each sensor's temperature, setpoint, alert and critical limits |
| Fans, PSUs, airflow direction | the same command: fan speed and status, PSU draw and capacity, airflow |
| BGP shield, orbits, prefix columns, uptime arcs | `show ip bgp summary \| json`: state, remote AS, prefixes, `upDownTime`, message counters |
| OSPF rings, conduits, BFD sleeves, beads, sparks | `show ip ospf neighbor \| json`: area, state, DR state, BFD state, state changes, retransmissions |
| OSPF route column, RIB totals | `show ip route summary \| json` |
| Header: model, EOS, uptime, CPU | `show version \| json`, `show processes top once \| json` |
| Syslog station | `show logging last 50` |

Nothing is installed on the device and nothing is configured on it. It is SSH and `show` commands, the same access an engineer uses every day.

## Health, by the box's own rules

The header status follows what the device itself reports rather than thresholds invented for the page:

- **CRITICAL**: the device's temperature status reports critical, overheating or shutdown; a sensor at its critical limit; every PSU failed; a BGP session down.
- **DEGRADED**: temperature or cooling status other than Ok; a sensor past its alert limit; a fan or a PSU not Ok; an LLDP neighbor or OSPF adjacency lost; an adjacency not FULL (2-WAY with a DROTHER is normal and ignored).
- A sensor past its **setpoint** is normal: that is where the fans ramp. It shows amber in the environment views and does not change the status.

## Quick start

Python 3.10 or newer, and a browser with WebGL2. three.js, xterm.js and the fonts are bundled, so neither the server nor the browser needs internet access.

From PyPI:

```bash
pip install netbridgeng
netbridgeng --print-config > config.yaml
netbridgeng
```

From source:

```bash
git clone https://github.com/scottpeterman/netbridgeng.git
cd netbridgeng
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
netbridgeng
```

Open <http://127.0.0.1:8470/> and connect to an Arista EOS switch, or <http://127.0.0.1:8470/?demo> for the demo. The page also runs the demo straight from disk: open `netbridgeng/static/index.html?demo` in a browser, no server needed.

`config.yaml` only pre-fills the connect dialog and sets the poll interval (15 s by default) and where the server listens. It is read from `--config`, then `$NETBRIDGENG_CONFIG`, then `./config.yaml`; `--host` and `--port` override the listen address. `requirements.txt` pins paramiko to 4.0.0 for older devices; the package itself accepts any 4.x.

## How it works

```
  switch  <--- SSH: show ... | json --->  collector (netmiko)
                                               |
                                    server (FastAPI): a session per device,
                                    a poll loop, the latest state in memory
                                               |
                          /ws: one JSON document per poll, pushed to the page
                                               |
                    page (one HTML file): three.js views, side stations, health
                                               |
              /ws/terminal: xterm.js  <-->  paramiko interactive shell
```

- `netbridgeng/collectors/arista/` runs the commands over one persistent SSH session and returns a single dictionary per poll (JSON where EOS offers it, parsers for the environment and syslog text).
- `netbridgeng/server.py` holds sessions, runs the poll loop, pushes each result over `/ws`, proxies the SSH terminal over `/ws/terminal`, and creates sessions through `POST /api/connect`.
- `netbridgeng/static/index.html` is the whole frontend: no build step, no framework. Rates (bits per second, discards, BGP messages, OSPF retransmits) are worked out in the page from counter deltas between polls, and history lives in the page for as long as it is open.

## Not just Arista

The page does not know it is talking to Arista. It reads one JSON document per poll, and any collector that produces the same keys lights up the same views. The shapes are EOS's own `| json` output, which makes them a reasonable, documented contract:

| Key | Shape | Used by |
|---|---|---|
| `version` | `hostname`, `modelName`, `version`, `serialNumber`, `uptime` or `bootupTimestamp` | header |
| `lldp.lldpNeighbors[]` | `port`, `neighborDevice`, `neighborPort`, `ttl` | radar, OSPF names |
| `interfaces.interfaceStatuses{port}` | `linkStatus`, `bandwidth`, `interfaceType`, `description` | radar, utilization, interfaces |
| `counters.interfaces{port}` | `inOctets`, `outOctets`, `inDiscards`, `outDiscards` | traffic, utilization |
| `bgp.vrfs.default` | `asn`, `routerId`, `peers{ip}` with `peerState`, `asn`, `prefixReceived`, `prefixAccepted`, `upDownTime`, `msgSent`, `msgReceived`, `description` | BGP |
| `ospf.vrfs.default.instList{id}.ospfNeighborEntries[]` | `routerId`, `interfaceName`, `interfaceAddress`, `adjacencyState`, `drState`, `priority`, `details{areaId, bfdState, retransmissionCount, numberOfStateChanges}` | OSPF |
| `routes.vrfs.default` | `totalRoutes`, `ospfCounts{...}`, `bgpCounts{...}` | OSPF, BGP |
| `environment` | `sensors[]` (`id`, `description`, `temp`, `setpoint`, `alert_limit`, `critical_limit`, `psu`), `fans[]`, `power_supplies[]`, `airflow`, `temp_status`, `cooling_status`, `ambient_temp` | environment, health |
| `logging[]` | `timestamp`, `source`, `severity`, `mnemonic`, `message` | syslog |
| `meta` | `hostname`, `timestamp`, `poll_count`, `poll_time`, `error`, `stale` | header, rates |

Junos (`| display json`), NX-OS (`| json`), IOS-XE (TextFSM, Genie or RESTCONF) and OpenConfig over gNMI can all be mapped into this shape. A second collector is the most direct way to prove the point further.

## Honest notes

- **One device per session.** The bridge is a view of a single switch, not of a network.
- **Sensor placement is grouped by name** (switch chip, CPU, PSU, front, rear). The data carries no physical positions, and the views say so.
- **Rates and history live in the page.** They start when the page opens and go when it closes.
- **Tested against** an Arista 7280R-series switch on EOS 4.21, and the demo. Other EOS versions and platforms may name sensors differently.

## Security

The server opens SSH sessions on request and the web UI has no login. It listens on `127.0.0.1` by default; keep it there unless you put it behind something that authenticates. Uploaded keys are written to a temporary file readable only by the server's user and deleted when the session ends. Host keys are accepted on first connect (paramiko `AutoAddPolicy`), which is fine for a proof of concept and not for anything more. The SSH agent is never used.

## License

GPL-3.0-or-later (see `LICENSE`). The bundled libraries keep their own licenses: three.js, xterm.js and xterm-addon-fit (MIT), Chakra Petch and Share Tech Mono (SIL Open Font License 1.1). Details and license texts are in `netbridgeng/static/vendor/`.

## Layout

```
netbridgeng/
  __main__.py               python -m netbridgeng (same as the netbridgeng command)
  server.py                 sessions, poll loop, /ws, /ws/terminal, /api/connect, /api/defaults
  config.example.yaml       netbridgeng --print-config
  collectors/arista/        collector.py (netmiko, show | json), parsers.py (environment, syslog)
  static/index.html         the bridge
  static/vendor/            three.js, xterm.js, fonts, and their licenses
screenshots/                demo mode
pyproject.toml
requirements.txt
LICENSE                     GPL-3.0
```

netbridgeng grew out of nethuds, an earlier experiment in heads-up displays for network devices.
