# OpenLocate (placeholder name)

OpenLocate is a free, open-source desktop app for Windows and macOS. It is meant to simulate
the GPS location of an iPhone over USB. No accounts, no Apple ID, no servers of ours,
no telemetry.

## Status: early development

Milestone 1 of 7 is done: the architecture, the Python sidecar (route engine, fake phone and
JSON-RPC server), and the Tauri and React app scaffold with a developer console.

Milestone 2 (real iPhone support) is in progress. The iPhone backend is written and its logic
is unit-tested. **It has been run against one real device only** (an iPad on iPadOS 27.2, over
USB from Windows). Other iOS versions and macOS are not tested yet. Wi-Fi is not supported: the cable must stay in.
The app has only a developer console so far, no map.

Routes along real roads work in the sidecar (walking, cycling or driving, at the routing
service's own pace or a speed you choose), checked on that same iPad. The app's console can
load one between two coordinates; there is no map to pick the points on yet.

Planned v1 features, not built yet: teleport by search or map click, picking a route on a
map, GPX playback, and scheduled location changes.

## Try it without an iPhone

You need Python 3.10 or newer. Run these in a terminal.

1. Go to the sidecar folder and create a virtual environment:

       cd sidecar
       python3 -m venv .venv

2. Install the sidecar with its developer tools (on Windows, use `.venv\Scripts\pip`):

       .venv/bin/pip install -e ".[dev]"

3. Run the tests:

       .venv/bin/python -m pytest -q

4. Start the sidecar with the fake phone:

       .venv/bin/python -m openlocate --backend mock

5. Type a request and press Enter:

       {"jsonrpc":"2.0","id":1,"method":"device.list"}

   You should get one line of JSON back that includes `"id":1`.

6. Press Ctrl+D to stop. On Windows, press Ctrl+Z and then Enter.

On Windows, the interpreter is `.venv\Scripts\python.exe`.

## Repository layout

- `sidecar/`: Python logic. See `sidecar/README.md` for setup and checks.
- `app/`: Tauri 2 shell (Rust) and React UI. See `app/README.md` for setup and checks.
- `protocol/contract.json`: the message contract that both test suites check.
- `docs/ARCHITECTURE.md`: decisions and the reasons for them. `docs/specs/`: task specs.

## Outside services

The finished app will contact these services. Only the ones marked "active now" are wired up.

- Map tiles from OpenFreeMap.
- Address search from the public Nominatim API. Its usage policy
  (<https://operations.osmfoundation.org/policies/nominatim/>) limits the whole application to
  one request per second, summed over all users, forbids search-as-you-type, and requires an
  identifying User-Agent. A growing project will need a proxy or another provider.
- Routing from the FOSSGIS OSRM servers at `routing.openstreetmap.de` (active now, when you
  load a route along roads). The start and end points of the route are sent to that server.
  It is a free community service with no uptime promise; the sidecar sends at most one request
  a second and keeps routes it has already fetched on disk. Another server can be set with
  `OPENLOCATE_ROUTER_WALK_URL`, `OPENLOCATE_ROUTER_BIKE_URL` and `OPENLOCATE_ROUTER_DRIVE_URL`.
- GitHub (`raw.githubusercontent.com`, the `doronz88/DeveloperDiskImage` repository), to
  download the developer disk image the first time an iPhone is connected. This is done by
  pymobiledevice3 and is active as soon as you connect a real iPhone.
- Apple's signing server, for the developer disk image on iOS 17 and later (also active now).
- Search and routing server addresses will be settings you can change.

## Use with your own device only

Use this app only with your own device. Some apps and games, such as Pokémon Go, ban location
spoofing and may suspend accounts. Follow the terms of service of any app you use. You take the
risk of any account action.

## License

GPL-3.0-or-later. The project bundles pymobiledevice3, which is GPL-3.0-or-later. See `LICENSE`.
