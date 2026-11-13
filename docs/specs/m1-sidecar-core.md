# Spec M1-A: sidecar core (route engine, mock backend, JSON-RPC server)

Read `docs/ARCHITECTURE.md` first. This task builds the Python sidecar's foundation. It does
**not** touch pymobiledevice3, the Tauri app, geocoding, routing, GPX or the scheduler.

## Deliverables

```
sidecar/
  pyproject.toml
  README.md                 (10 to 20 lines: how to create the venv, run tests, run the sidecar)
  src/openlocate/
    __init__.py             (__version__ = "0.1.0")
    __main__.py
    errors.py
    logging_setup.py
    engine/__init__.py  geo.py  route.py  jitter.py  player.py
    device/__init__.py  base.py  mock.py
    playback.py             (PlaybackRunner)
    rpc/__init__.py  protocol.py  server.py  handlers.py
  tests/
```

### Packaging

- `pyproject.toml`, setuptools, `src` layout, package name `openlocate`, Python `>=3.10`,
  license `GPL-3.0-or-later`.
- **No runtime dependencies** in this task (standard library only).
- Dev extras: `pytest`, `pytest-asyncio`, `ruff`, `mypy`. Configure ruff (line length 100) and
  mypy `strict = true` for `src/`. Both must pass clean.
- Create the virtualenv at `sidecar/.venv` (`python3 -m venv`; there is no system pip or uv).

### engine/ (pure: no I/O, no `time`, no `asyncio`, no `random` module-level state)

`geo.py`
- `LatLon` frozen dataclass (`lat`, `lon` in degrees). Validates on construction: lat in
  [-90, 90], lon in [-180, 180], both finite. Raises `ValueError` otherwise.
- `haversine_m(a, b) -> float`, `initial_bearing_deg(a, b) -> float` (0 to 360),
  `destination(origin, bearing_deg, distance_m) -> LatLon`,
  `interpolate(a, b, fraction) -> LatLon` (great-circle; must be correct across the
  antimeridian; `fraction` clamped to [0, 1]).
- Earth radius 6 371 008.8 m.

`route.py`
- `Route(points: Sequence[LatLon])`. Requires at least 2 points. Drops consecutive duplicate
  points; if fewer than 2 distinct points remain, raises `ValueError`.
- `length_m`, `point_at(distance_m) -> LatLon` (clamped to the ends; binary search over
  cumulative distances), `bearing_at(distance_m) -> float`.

`jitter.py`
- `JitterConfig(speed_fraction=0.05, position_m=1.5, enabled=True)`.
- `Jitter(config, seed: int | None)` wrapping its own `random.Random(seed)`.
- `speed_factor() -> float`: a smooth multiplier around 1.0 (low-pass filtered noise, so
  speed drifts instead of jumping), always within `1 ± speed_fraction`.
- `offset(point) -> LatLon`: moves the point by a random bearing and a distance drawn so that
  it never exceeds `2 * position_m`.
- With `enabled=False`, factor is exactly 1.0 and offset returns the point unchanged.

`player.py`
- `PlayerState` enum: `IDLE`, `PLAYING`, `PAUSED`, `FINISHED`.
- `Player(route, speed_mps, *, loop=False, jitter: Jitter | None = None)`.
- `start()`, `pause()`, `resume()`, `stop()`, `set_speed(speed_mps)`. Speed must be > 0 and
  <= 150 m/s (540 km/h), else `ValueError`. Invalid transitions (for example `resume()` when
  not paused) raise a clear `PlayerStateError`.
- `advance(dt_seconds: float) -> Fix` where `Fix` is a frozen dataclass:
  `position: LatLon` (with jitter applied), `distance_m` (true distance along the route,
  no jitter), `speed_mps` (the speed used for this step), `bearing_deg`, `state`,
  `progress` (0 to 1), `lap` (int, starts at 0).
  - `dt_seconds` must be >= 0 and finite.
  - When `PAUSED`, `IDLE` or `FINISHED`, distance does not change. The returned position is
    the current point. While `PAUSED` the position keeps a tiny jitter (a parked phone's GPS
    still wanders); while `FINISHED` the position is **exactly** the final route point with no
    jitter, so the phone stays parked at the destination.
  - Without loop: when distance reaches `length_m`, state becomes `FINISHED` and stays there.
  - With loop: distance wraps to the start (carry the overshoot over), `lap` increments.
    A single large `dt` may wrap more than once and must be handled without recursion.
  - A speed change takes effect from the next `advance`; distance already covered is kept.
- Also provide `SPEED_PRESETS_KMH = {"walk": 5.0, "bike": 16.0, "drive": 50.0}` and
  `kmh_to_mps`.

### device/

`base.py`
- `DeviceInfo` frozen dataclass: `id`, `name`, `model`, `os_version`, `connection`
  (`"usb" | "wifi" | "mock"`), `state` (enum `DeviceState`: `DISCONNECTED`, `CONNECTING`,
  `NEEDS_TRUST`, `NEEDS_DEVELOPER_MODE`, `MOUNTING_IMAGE`, `READY`, `ERROR`).
- `DeviceBackend` as an `abc.ABC` with async methods `list_devices`, `connect(device_id)`,
  `disconnect`, `set_location(LatLon)`, `clear_location`, and a sync property
  `connected: DeviceInfo | None`. Docstrings state the contract, including: `set_location`
  and `clear_location` raise `OpenLocateError(NOT_CONNECTED)` when nothing is connected.

`mock.py`
- `MockDevice(DeviceBackend)`: one fake iPhone (`id="MOCK-0001"`, name "Mock iPhone",
  os_version "27.2.1"). Keeps `current: LatLon | None` and a bounded `history` (deque,
  max 10 000) of `(monotonic_time, LatLon | None)`. Logs each call at INFO.
- Constructor options for testing failures: `fail_connect_with: ErrorCode | None`,
  `fail_set_after: int | None` (raises `DEVICE_DISCONNECTED` once N sets have succeeded).

### errors.py

- `ErrorCode` string enum. For this task: `NOT_CONNECTED`, `DEVICE_NOT_FOUND`,
  `DEVICE_DISCONNECTED`, `TRUST_REQUIRED`, `DEVELOPER_MODE_OFF`, `INVALID_PARAMS`,
  `INVALID_STATE`, `NO_ROUTE_LOADED`, `INTERNAL`.
- A catalogue mapping every code to a human-readable `message` and a `fix`. Example:
  `DEVELOPER_MODE_OFF` → message "Developer Mode is turned off on the iPhone." fix
  "On the iPhone open Settings → Privacy & Security → Developer Mode, turn it on, then restart
  when asked."
- `OpenLocateError(code, detail: str | None = None)` with `.to_dict()` returning
  `{"code", "message", "fix", "detail"}`. A test must assert every `ErrorCode` has a
  catalogue entry with non-empty message and fix.

### logging_setup.py

- `configure_logging(log_dir: Path | None = None) -> Path` returns the log file path.
- Rotating file handler (1 MB × 3 files) plus a stderr handler. **Never** stdout.
- Default directory, with no third-party dependency: Windows `%LOCALAPPDATA%\OpenLocate\logs`,
  macOS `~/Library/Logs/OpenLocate`, otherwise `$XDG_STATE_HOME/openlocate/logs` or
  `~/.local/state/openlocate/logs`. Use `pathlib` throughout.

### playback.py

- `PlaybackRunner(backend, *, tick_seconds=1.0, clock=time.monotonic, sleep=asyncio.sleep,
  on_fix: Callable[[Fix], None] | None = None)`.
- `load(route, speed_mps, loop, jitter)`, `start()`, `pause()`, `resume()`, `stop()`,
  `set_speed()`, `status() -> dict`.
- One background `asyncio.Task` ticks: measures real elapsed time with `clock`, calls
  `player.advance(elapsed)`, sends the position to `backend.set_location`, calls `on_fix`.
- Elapsed time per tick is capped at 5 s, so a laptop waking from sleep does not teleport the
  phone far along the route.
- When the player reaches `FINISHED`: send the exact final point once, then stop ticking. The
  location is **not** cleared.
- `stop()` cancels the task and waits for it. It does not clear the location.
- If `backend.set_location` raises, the runner pauses (it does not crash or spin), records the
  error and reports it through `on_error: Callable[[OpenLocateError], None] | None`.
- `clock` and `sleep` are injectable so tests run instantly with a fake clock. No test may
  really sleep.

### rpc/

`protocol.py`: parse and build JSON-RPC 2.0 messages. Malformed JSON → `-32700`, bad request
→ `-32600`, unknown method → `-32601`, bad params → `-32602`, `OpenLocateError` → `-32000`
with `error.data = err.to_dict()`, any other exception → `-32603` with code `INTERNAL`
(log the traceback to the file; do not send it over the wire).

`server.py`: `RpcServer(reader, writer, handlers)`. Reads newline-delimited JSON from an
async reader, dispatches each request concurrently (a slow call must not block others),
writes one line per response, and has `notify(method, params)`. Writes are serialised with a
lock so lines never interleave. Lines longer than 1 MiB are rejected with `-32600`. On EOF
the server shuts down cleanly: stops playback and returns. Reading real stdin must work on
Windows (the default Proactor loop cannot `connect_read_pipe` to a console handle reliably,
so read stdin with a daemon thread feeding an `asyncio.Queue`, and use that on every OS).

`handlers.py`: methods, all params validated (wrong type or missing → `INVALID_PARAMS`):

| Method | Params | Result |
|---|---|---|
| `app.info` | none | `{version, backend, logFile}` |
| `device.list` | none | `{devices: [DeviceInfo]}` |
| `device.connect` | `{id}` | `DeviceInfo` |
| `device.disconnect` | none | `{}` (stops playback first) |
| `location.set` | `{lat, lon}` | `{}` (stops any playback first) |
| `location.clear` | none | `{}` (stops any playback first) |
| `playback.load` | `{points: [[lat, lon], ...], speedKmh, loop?, jitter?}` | `{lengthM, points}` |
| `playback.start` / `pause` / `resume` / `stop` | none | status |
| `playback.setSpeed` | `{speedKmh}` | status |
| `playback.status` | none | `{state, distanceM, lengthM, progress, speedKmh, lap, position}` |

Notifications sent by the sidecar: `location.updated {lat, lon, source: "teleport"|"playback"}`,
`playback.state {…status}` on every state change, `playback.error {code, message, fix, detail}`.
JSON field names are camelCase; Python names are snake_case. `points` is capped at 200 000.

`__main__.py`: `python -m openlocate [--backend mock|ios] [--log-dir PATH]`. Backend default
comes from `OPENLOCATE_BACKEND`, else `ios`. In this task `ios` is not implemented: exit with
code 2 and a clear message on stderr. Sets up logging, builds the server on stdin/stdout, runs
until EOF.

## Tests (pytest, all must pass, none may sleep for real)

- geo: known distances (for example London to Paris within 0.5 %), bearing, destination
  round trip, antimeridian interpolation, validation errors.
- route: length, `point_at` at 0, the middle, the end and beyond; duplicate points; too few points.
- jitter: bounds hold over 10 000 samples; same seed gives the same sequence; disabled is exact.
- player: constant speed covers `speed × time` (jitter off); pause holds distance; speed change
  mid-route; finish parks on the exact last point; loop wraps and counts laps, including a
  `dt` larger than a full lap; invalid transitions and invalid speeds raise.
- playback runner with fake clock and `MockDevice`: positions arrive in order, final point is
  exact, pause/resume, backend failure pauses the runner and reports the error, elapsed cap.
- rpc: each protocol error code; a full session over in-memory streams (list, connect, set,
  load, start, status, stop); notifications emitted; concurrent requests; 1 MiB limit.
- One end-to-end test that starts `python -m openlocate --backend mock` as a real subprocess,
  sends `app.info` and `location.set`, reads the replies, closes stdin and asserts exit code 0
  within a timeout. stdout must contain nothing but JSON lines.

## Done means

`cd sidecar && .venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`, and
`.venv/bin/mypy src` all pass. Do not commit.
