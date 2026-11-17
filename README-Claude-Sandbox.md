# README: Claude sandbox setup

How to stand netbridgeng up in a Claude cloud sandbox. Read this first in a new session.

## Setup

Python 3.11+ and Node are in the sandbox.

```bash
pip install -r requirements.txt --break-system-packages
```

There is no switch to reach from the sandbox: work in demo mode (`?demo`). The connect dialog can still be exercised against an unreachable address (192.0.2.10) to check the error path.

three.js, xterm.js and the fonts are bundled in `netbridgeng/static/vendor/`, so headless renders need no network routing. Playwright and Chromium are preinstalled (do not run `playwright install`); launch Chromium with `--use-gl=swiftshader --enable-unsafe-swiftshader`.

Build and check the package:

```bash
pip install build --break-system-packages
python3 -m build
```

## Common jobs

Run the server (listens on 127.0.0.1:8470):

```bash
netbridgeng
```

Check the page's scripts parse after an edit:

```bash
node -e "const fs=require('fs');const h=fs.readFileSync('netbridgeng/static/index.html','utf8');new Function([...h.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join('\n'));console.log('parses')"
```

## Demo timeline

The demo ticks every 3 s on a 90 s cycle: a leaf link and its LLDP neighbor and OSPF adjacency drop at about 24 s and return at about 48 s; a BGP session flaps from about 60 s to 75 s; the fabric is calm from 75 s until the next cycle. Wait on page state rather than time, for example `Radar.lostCount()>0`, `Ospf.lost()>0`, or a peer in `D.bgp.vrfs.default.peers` not Established. `setView('lldp'|'util'|'therm'|'bgp'|'ospf')` and `setDetail(true)` switch views from a script.

## Junos adapter

No Junos box is reachable either. The adapter runs against synthetic replies:

```bash
python3 -m pytest -q tests
python3 -m netbridgeng.collectors.juniper adapt tests/fixtures/junos-synthetic
```

`adapt` writes `bridge.json` next to the replies (delete it before committing).

To see the bridge draw Junos data, start the server and load `/?demo=junos`: the synthetic MX in `netbridgeng/collectors/juniper/demo/` goes through the adapter on every load (`GET /api/demo/junos`) and the page animates it. The demo ticks every 3 s; `D.meta.poll_count % 30` is 8-15 during the link loss and 20-24 during the IX BGP flap, so a screenshot script can wait on it. Regenerate the dataset with `python3 tools/make_junos_demo.py`.

## Sandbox quirks

- WebGL runs on SwiftShader: give screenshots long timeouts and a few seconds to settle after a view change.
- `config.yaml` stays out of the repo (`.gitignore`); `config.example.yaml` is what ships.
