# OpenLocate architecture

OpenLocate (placeholder name) is a free desktop app for Windows and macOS that simulates an
iPhone's GPS location over USB. This document records what we decided, why, and what
is still unverified. Update it when a decision changes.

Research date: 2026-11-12. Library versions quoted below were current on that date.

## 1. Overview

```
┌──────────────────────────── Desktop app (Tauri 2) ────────────────────────────┐
│                                                                               │
│  React + TypeScript UI          Rust shell               Python sidecar       │
│  (view only)                    (a pipe)                 (all the logic)      │
│                                                                               │
│  MapLibre map        invoke()   spawn + supervise        JSON-RPC server      │
│  search box        ──────────►  the sidecar,     stdio   ├─ device backends   │
│  drive controls                 forward lines  ◄──────►  │   ├─ mock          │
│  schedule list     ◄──────────  both ways                │   └─ ios (pmd3)    │
│                      events                              ├─ route engine      │
│                                                          ├─ scheduler         │
│                                                          ├─ geocode / routing │
│                                                          └─ file logging      │
└───────────────────────────────────────────────────────────────────────────────┘
                                                                  │ USB        
                                                                  ▼
                                                               iPhone
```

Three processes, one rule: **the sidecar is the brain, Rust is a pipe, React is the view.**

Why the logic lives in the sidecar and not in the UI:

- Route playback and the scheduler must keep running when the window is minimised or hidden.
  Webviews throttle timers in background windows, so a 1 Hz loop in React would stall.
- Scheduled drives need routing with no UI interaction, so routing has to be reachable from
  the scheduler.
- The Nominatim policy requires an identifying `User-Agent`. JavaScript in a webview cannot
  set that header; native code can.
- One language for everything that needs unit tests.

## 2. Decisions

### 2.1 Device layer: pymobiledevice3 as a library, in a sidecar

Verified by reading the installed source of pymobiledevice3 **11.54.0** (released 2026-11-12).
It installs and imports on Python 3.14.6 on Windows 11 (checked 2026-11-13), so no older
Python is needed. The sidecar pins `pymobiledevice3>=11.54,<12`.

| Topic | Finding | Status |
|---|---|---|
| License | `GPL-3.0-or-later` (package metadata `License-Expression`) | confirmed in source |
| Python | `>=3.9`; the whole API is `asyncio` | confirmed in source |
| Release pace | several releases a week | from the GitHub API |

**Tunnel method by iOS version**

| iOS | How developer services are reached | Admin needed? |
|---|---|---|
| below 17 | plain lockdown; `DtSimulateLocation` | no |
| 17.0 to 17.3 | RemotePairing tunnel. macOS can piggyback Apple's own `remoted` tunnel. On Windows the docs say a kernel tunnel (`tunneld`) is needed | Windows: yes |
| 17.4 and later (18, 26, 27) | `CoreDeviceTunnelProxy` over lockdown, carried by the **userspace tunnel** (`UserspaceRsdTunnel`, a pure-Python TCP/IP stack) | **no** |

Decision: use the in-process userspace tunnel (`UserspaceRsdTunnel`) for iOS 17.4+. It needs no
administrator rights on any host, which removes the whole elevation problem (no UAC prompt, no
elevated helper, no named pipes) and lets the sidecar use plain stdio.

- iOS 17.0 to 17.3 on Windows is **not supported in v1**. It would need an elevated `tunneld`.
  The app shows a clear message asking the user to update iOS. Revisit if users ask.
- The userspace tunnel allows **one tunnel per process**, so v1 controls one device at a time.

**Location API** (confirmed in source, not yet run on a device):

- iOS 17+: `DvtProvider(rsd)` plus `LocationSimulation(dvt)`, with `await set(lat, lon)` and
  `await clear()`. The older name `DvtSecureSocketProxyService` no longer exists.
- iOS below 17: `DtSimulateLocation(lockdown)` with the same `set` / `clear`.

**How simulation behaves on the device.** Measured 2026-11-15 on an iPad Air (M4, Wi-Fi only,
no GPS), iPadOS 27.2, over USB from Windows. The evidence is the device's own log (`locationd`
lines read with `pymobiledevice3 syslog live`) plus screenshots; an earlier version of this
section, based on what Maps drew, was wrong.

- **Set.** `locationd` logs "request to start location simulation" and then produces a
  simulated fix every second by itself. One `set` is enough: the dot stayed blue for 75 s with
  no further updates. A 1.9 km playback at 50 km/h (about one update a second) moved smoothly.
- **Reset.** `stopLocationSimulation` reaches `locationd` at once ("request to stop location
  simulation") and the simulated fixes stop within the same second. The library sends it
  without asking for a reply; the sidecar asks for one, and the device answers.
- **Closing the session is also a reset.** When the sidecar disconnects or quits, the device
  stops the simulation by itself, with no `clear` sent. The simulation needs a live session.
  Pulling the cable ends the session too: the sidecar reports `DEVICE_DISCONNECTED` on the
  next update, the device leaves the list at once, and reconnecting after replugging takes
  about 0.5 s.
- **What the user sees after a stop is the problem.** Apps keep showing the last simulated
  position (Maps: a grey dot, sometimes still blue, or no dot after Maps restarts) until a real
  fix arrives. On this GPS-less iPad the real fix did not come back by itself, in one case for
  20 minutes. Turning Wi-Fi off and on brought it back within about two minutes; leaving and
  rejoining the network also worked; restarting the iPad always did. Why it stalls is not
  established. `locationd` logs `@ClxWifi, Fix, 0 ... NoValidHorizontalAPs` during the stall,
  but that line kept appearing after Maps had a real position again, so it is a hint, not
  proof. Not tested on a device with GPS, where a satellite fix may make this a non-issue.
- **The clock moves too.** With "Set Automatically" on, the device switches to the time zone
  of the simulated place, and back only when a real fix returns.

Consequences: there is no "location stays after you quit" mode, so the UI must not promise
one. After a reset or disconnect the UI should say the device may keep showing the old place
until it finds its real position, and suggest turning Wi-Fi off and on (allow a couple of
minutes), then a restart. "Reset
OK" from the sidecar means the simulation stopped, not that the real position is back.

**Checking a device without looking at it.** `sidecar/scripts/ios_screenshot.py` opens Maps,
taps its locate button and saves a screenshot. Maps is a weak witness (it reopens on the last
viewed area and can keep drawing a stale position), so use the `locationd` log for start and stop, and a
screenshot to confirm that a real position is back.

**Windows requirement.** Apple Mobile Device Service (usbmux, TCP 127.0.0.1:27015) must be
present. It comes with iTunes or the Apple Devices app. No tunnel driver is needed with the
userspace tunnel. Observed 2026-11-13 with the Store version of Apple Devices: with the app
open and no iPhone on USB, nothing listens on 27015. With a device plugged in it does listen
(checked 2026-11-15). The sidecar reports this as `DEVICE_SERVICE_UNAVAILABLE`.

**Developer disk image source.** The image is downloaded by pymobiledevice3 from
`raw.githubusercontent.com/doronz88/DeveloperDiskImage` and cached in the user's home folder.
From iOS 27.0 the library installs it as a cryptex, which needs the RSD tunnel, so on iOS 17+
we mount through the tunnel, not through plain lockdown.

**How the backend is split.** `device/ios.py` holds the session rules (one device, what
happens when the session drops) behind a small driver interface and has no library imports.
`device/pmd3.py` is the only module that imports pymobiledevice3; it translates every library
exception into a catalogue error. Connect runs: pair (the Trust prompt is shown and the call
fails at once with `TRUST_REQUIRED` rather than waiting), check Developer Mode (and reveal the
switch in Settings if it is off), open the tunnel, mount the image, open the DVT channel.

**Wi-Fi.** Not supported, and dropped from the plan (decided 2026-11-15): the app is USB only.
What one attempt on that date showed (iPadOS 27.2, Windows 11), kept in case it is revisited:
- On eduroam (campus WPA2-Enterprise) the PC could not see the iPad at all. On the PC's own
  mobile hotspot the iPad answered ping and had ports 62078 (lockdown) and 49152 open, but
  bonjour discovery still found nothing, and usbmux listed no network device.
- The Apple Devices option "Show this iPad when on Wi-Fi" did not stick. `EnableWifiConnections`
  read false; setting it over USB (`set_enable_wifi_connections(True)`) worked.
- With that on, lockdown over TCP by IP address works when the pair record is fetched from
  usbmux and passed in explicitly.
- `CoreDeviceTunnelProxy`, the tunnel the sidecar uses, is then refused: the iPad closes the
  connection during tunnel establish. It appears to be USB only.
- Not tried: the RemotePairing tunnel (separate pairing, normally found by bonjour). That
  would be the route to a wireless session.

### 2.2 The device interface (and room for v2)

Everything above sits behind one small interface:

```python
class DeviceBackend(Protocol):
    async def list_devices(self) -> list[DeviceInfo]: ...
    async def connect(self, device_id: str) -> DeviceInfo: ...
    async def disconnect(self) -> None: ...
    async def set_location(self, point: LatLon) -> None: ...
    async def clear_location(self) -> None: ...
```

The route engine, scheduler and RPC layer only ever see this interface. Backends:

- `mock`: a fake phone that records coordinates. Selected with `--backend mock` or
  `OPENLOCATE_BACKEND=mock`. The whole app can be built and tested without an iPhone.
- `ios`: pymobiledevice3. The default when no backend is named.
- v2, phone-only mode (pairing file plus on-device loopback VPN): a third backend. Nothing
  else should need to change.

### 2.3 Sidecar protocol: JSON-RPC 2.0 over stdio

- One JSON object per line (newline-delimited), UTF-8, on stdin and stdout.
- stdout carries **only** protocol messages. All logging goes to a file and to stderr.
- Requests have an `id` and get a response. The sidecar also sends notifications (no `id`) for
  events: `device.changed`, `location.updated`, `playback.state`, `schedule.fired`, `log.error`.
- Errors use the JSON-RPC `error` object. `error.data` always carries
  `{ "code": "DEVELOPER_MODE_OFF", "message": "...", "fix": "..." }`, so every failure reaches
  the user with a plain-language message and a suggested fix.
- Stdio rather than a localhost port: nothing listens on the network, so no other program on
  the machine can drive the phone, and there is no port to clash.
- **One contract file, `protocol/contract.json`.** It lists every request, response, error and
  notification as a scripted session, with fixed field names (camelCase) and enum values (lower
  snake_case). The Python tests replay it against the mock backend and the TypeScript tests
  check it against the UI's runtime guards, so the two sides cannot drift apart unnoticed.
  Change the contract first, then both sides.
- Protocol-level failures (bad JSON, unknown method) use the JSON-RPC numeric codes and carry
  `data.code = "INTERNAL"`; bad parameters use `-32602` with `INVALID_PARAMS`.
- A line may be at most 1 MiB. Long routes are produced inside the sidecar (routing, GPX), so
  the UI does not need to send large point lists.

### 2.4 UI shell: Tauri 2, with the sidecar managed by our own Rust code

Tauri 2.12 (stable), React, TypeScript, Vite. Rust 1.90 or newer.

- We do **not** use `tauri-plugin-shell`. The Rust side spawns the sidecar with
  `std::process::Command`, reads stdout line by line, and exposes one command (`rpc`) and one
  event stream to the UI. That is less permission surface and gives us full control of the
  child's lifetime.
- The process handling lives in its own crate, `app/src-tauri/sidecar-host`, which does not
  depend on Tauri. It can therefore be compiled and tested on any machine, including against
  the real Python sidecar. `src-tauri/src` is only the glue that turns its events into Tauri
  events.
- Packaging: PyInstaller **one-folder** build shipped through `bundle.resources`, not a
  one-file `externalBin`. A one-file build starts slowly (it unpacks itself each launch) and on
  Windows the process Tauri sees is only a launcher, so killing it can leave the real Python
  process running. The sidecar exits on its own when stdin closes, and the app kills it if it
  has not exited within 2 s. A Windows Job Object (so the child dies even if the app crashes)
  is planned for Milestone 6.
- In development the Rust side runs `python -m openlocate` from the sidecar's virtualenv.
- Electron is not needed: with no elevation and a plain child process, nothing about Tauri is
  in the way.

### 2.5 Map, search and routing

| Need | Service | Rules we follow |
|---|---|---|
| Map tiles | OpenFreeMap (`https://tiles.openfreemap.org/styles/liberty`) with MapLibre GL JS (BSD-3-Clause) | Free, no key. Attribution shown on the map. Never `tile.openstreetmap.org`. |
| Search | Nominatim public API | Max 1 request/second across the app. Identifying `User-Agent`. **No search-as-you-type** (forbidden): search runs on Enter or the Search button only. Results cached. Attribution shown. Server URL is a setting, so it can be switched without a software update (a policy requirement). |
| Routing | OSRM. Default `router.project-osrm.org` | Max 1 request/second. Non-commercial, no uptime promise. URL is a setting so users can self-host. Routes cached on disk by (server, profile, coordinates). |

The Nominatim policy is at <https://operations.osmfoundation.org/policies/nominatim/>. Its limits
apply to the sum of all users of the application, so if this project grows it must move to a
proxy or another provider. The README must say this.

Geocoding and routing clients live in the sidecar, behind one shared rate limiter.

### 2.6 Route playback engine

Pure Python with no I/O, no clock and no device imports, so every behaviour is unit-testable.

- `geo`: haversine distance, bearing, destination point, interpolation.
- `Route`: a polyline with cumulative distances; `point_at(distance)`.
- `Player`: a state machine (idle, playing, paused, finished). The caller pushes time in with
  `advance(dt_seconds)` and gets back a position. Supports speed change mid-route, pause and
  resume, loop, and parking at the destination when finished.
- `Jitter`: small speed variation and position noise from a **seeded** random generator, so
  tests are reproducible.
- A separate thin async `PlaybackRunner` owns the real clock, calls `advance` about once a
  second and forwards positions to the `DeviceBackend`. It measures elapsed time rather than
  assuming exactly one second, so a late tick does not make the phone fall behind.

### 2.7 Scheduler

Lives in the sidecar. Jobs are stored in a JSON file in the user's config directory. The app
must be running and the phone reachable for a job to fire, and the UI says so. Jobs that were
missed while the app was closed are reported, not silently run late.

### 2.8 Errors and logging

- One catalogue of error codes (`openlocate/errors.py`). Each has a message and a suggested fix.
  Library exceptions are translated at the backend boundary and never leak raw to the UI.
- Rotating log file in the user's log directory. Pairing records and secrets are never logged.
  Coordinates are logged, so the UI warns users to review a log before attaching it to an issue.

### 2.9 License

**GPL-3.0-or-later**, to match pymobiledevice3, which we bundle. Bundled dependencies must be
GPL-compatible (MapLibre is BSD-3-Clause, Tauri is MIT/Apache-2.0, React is MIT).

### 2.10 Privacy

No accounts, no Apple ID, no servers of ours, no telemetry. The only outbound requests are map
tiles, search, routing, and (through pymobiledevice3) Apple's signing server for the developer
disk image. All are listed in the README.

## 3. Repository layout

```
sidecar/                 Python package: openlocate
  src/openlocate/
    engine/              pure route engine (no I/O)
    device/              DeviceBackend interface, mock backend, ios backend + pmd3 driver
    rpc/                 JSON-RPC protocol and stdio server
    errors.py            error catalogue
    logging_setup.py
    __main__.py          entry point
  tests/
app/                     Tauri 2 + React + TypeScript
  src/                   UI
  src-tauri/             Rust shell
    sidecar-host/        child-process supervisor, no Tauri dependency
protocol/contract.json   the shared JSON-RPC message contract
docs/                    this file, and task specs in docs/specs/
.claude/agents/          builder, scout, docs subagents
```

## 4. Open questions

1. Closing the session or unplugging stops the simulation (answered, see 2.1). Open: does a
   device with GPS get its real position back by itself after a stop?
2. The userspace tunnel works end to end on Windows with iPadOS 27.2 over USB (answered:
   first connect about 7 s including image download and mount, later connects under 2 s).
3. Wi-Fi: closed. Not with the current tunnel, and dropped from the plan (see 2.1).
4. Does the PyInstaller build of the userspace tunnel stack need extra hidden imports? (M6.)
5. macOS: prefer the `native` tunnel or the userspace tunnel? (Decide in M2, macOS pass.)
