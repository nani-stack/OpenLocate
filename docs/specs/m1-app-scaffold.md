# Spec M1-B: app scaffold (Tauri 2 + React + TypeScript) with a dev console

Read `docs/ARCHITECTURE.md` (sections 2.3 and 2.4) and `docs/specs/m1-sidecar-core.md` (the
RPC method table) first. Another builder is writing `sidecar/` at the same time. **Work only
inside `app/`.** Do not read or depend on unfinished sidecar files; the RPC table is the
contract.

This task builds the shell and a plain developer console. No map, search, routing or
scheduler yet (later milestones).

## Stack and versions

- Tauri 2 (latest 2.x: `tauri` crate 2.12.x, `@tauri-apps/cli` and `@tauri-apps/api` 2.12.x).
  Do **not** use any 3.0 alpha. Do **not** add `tauri-plugin-shell`.
- React 18 or 19, TypeScript `strict`, Vite, Vitest. npm (no pnpm or yarn on this machine).
- Keep dependencies minimal. No UI kit, no state library, no CSS framework: plain CSS.

## Layout

```
app/
  package.json  tsconfig.json  vite.config.ts  index.html
  src/
    main.tsx  App.tsx  styles.css
    rpc/client.ts        typed wrapper over invoke("rpc") and the notification event
    rpc/types.ts         TypeScript types mirroring the RPC table (DeviceInfo, PlaybackStatus, RpcError…)
    components/…         small components for the console
  src-tauri/
    Cargo.toml  build.rs  tauri.conf.json  capabilities/default.json  icons/
    src/main.rs  src/lib.rs  src/sidecar.rs
```

## Rust shell (`src-tauri`)

`sidecar.rs` owns the child process. Requirements:

- Spawn with `std::process::Command`, stdin/stdout piped, stderr inherited in debug builds.
  On Windows set the `CREATE_NO_WINDOW` creation flag so no console window flashes.
- How the command is resolved, in order:
  1. `OPENLOCATE_SIDECAR_PYTHON` env var: path to a Python interpreter; run
     `<python> -m openlocate`.
  2. Debug builds: `<repo>/sidecar/.venv/bin/python` (or `.venv\Scripts\python.exe` on
     Windows), found relative to `CARGO_MANIFEST_DIR` at compile time.
  3. Release builds: return a clear error "bundled sidecar not available yet" (Milestone 6).
  Append `--backend <value>` when `OPENLOCATE_BACKEND` is set.
- A reader thread reads stdout **line by line** (`BufRead::lines`), parses each line as JSON:
  - has `id` and (`result` or `error`) → complete the matching pending request;
  - has `method` and no `id` → emit Tauri event `sidecar://notification` with
    `{method, params}`;
  - anything else (including invalid JSON) → log a warning, never panic.
  Put this classification in a **pure function** with unit tests.
- Pending requests: a `Mutex<HashMap<u64, oneshot::Sender<…>>>`, ids from an `AtomicU64`.
- When the child exits or stdout closes: fail every pending request with a clear error, emit
  `sidecar://exit` with `{code}`.
- One Tauri command: `rpc(method: String, params: Option<serde_json::Value>) ->
  Result<serde_json::Value, serde_json::Value>`. `Ok` is the JSON-RPC `result`. `Err` is an
  object `{code, message, fix, detail}`: taken from `error.data` when present, otherwise
  built from the JSON-RPC error (code `INTERNAL`). A request with no reply in 30 s fails with
  code `TIMEOUT`.
- A second command `sidecar_restart()` that kills the child (if any) and spawns a new one.
- On app exit, close the child's stdin and kill it if it has not exited within 2 s.
- No `unwrap()`/`expect()` on anything that can fail at run time. No `unsafe`.
- Security: the default capability grants only `core:default`. Set a CSP in `tauri.conf.json`:
  `default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
  worker-src 'self' blob:; connect-src 'self' ipc: http://ipc.localhost`. (Tile hosts are
  added in Milestone 3.)
- App identifier `org.openlocate.app`, product name `OpenLocate`, version `0.1.0`, window
  1100×720, license `GPL-3.0-or-later` in `Cargo.toml` and `package.json`.
- Icons: generate a simple placeholder icon set (any plain original shape; no third-party
  artwork). `npx tauri icon` on a generated PNG is fine.

## Frontend: developer console

A single page, plain and readable. It exists so the lead and the user can exercise the
sidecar end to end before the real UI is built.

- Header: app name, sidecar status (running / exited, with a Restart button), backend name
  and log file path from `app.info`.
- Device panel: Refresh (`device.list`), a list of devices with state, Connect / Disconnect.
- Teleport panel: latitude and longitude inputs with validation (lat −90…90, lon −180…180,
  numbers only; show an inline message and do not call the sidecar when invalid), a Teleport
  button (`location.set`) and a "Reset to real location" button (`location.clear`).
- Playback panel: a "Load demo route" button that loads a fixed short route (about 1 km,
  8 to 12 hard-coded points in a public place), a speed selector (walk 5, bike 16, drive 50,
  custom km/h), loop checkbox, Start / Pause / Resume / Stop, and a live readout (state,
  progress %, distance, speed, lap, current lat/lon) fed by the `playback.state` and
  `location.updated` notifications.
- Error banner: every failed call shows `message` and `fix` from the error object, and can be
  dismissed. Nothing fails silently.
- `rpc/client.ts`: `call<M extends keyof Methods>(method, params)` fully typed from
  `rpc/types.ts`, `onNotification(handler)` returning an unsubscribe function. The transport
  (Tauri `invoke`/`listen`) is injected so the client and components can be unit-tested
  without Tauri.

## Tests and checks

- Vitest: the RPC client (success, error mapping, notification fan-out, unsubscribe) and the
  coordinate validation. Use a fake transport.
- `npm run typecheck` (tsc --noEmit), `npm run test`, `npm run build` (vite build) must pass.
- Rust: `cargo test` and `cargo clippy -- -D warnings` in `src-tauri`.
  **Known limitation:** this Linux machine does not have the WebKitGTK development packages
  (`libwebkit2gtk-4.1-dev` and friends) and there is no sudo, so the Tauri crate may not
  compile here. Check with `pkg-config --exists webkit2gtk-4.1`. If it is missing, do not try
  to install system packages. Instead keep the pure logic (line classification, error
  mapping, command resolution) in a module that does not depend on `tauri`, and make it
  testable on its own (for example a small workspace member crate `openlocate-sidecar-proto`,
  or `cargo test` on a lib target with the tauri parts behind a cargo feature). Run what can
  run, and say exactly which parts you could not compile.

## Done means

All the checks above that can run on this machine pass, and your report lists precisely what
was compiled and tested versus written but not compiled. Do not commit.
