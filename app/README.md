# OpenLocate app (Tauri 2 + React): the desktop shell and a developer console for `../sidecar`

## Prerequisites

- Node 22 with npm, and Rust 1.90 or newer.
- The sidecar's virtualenv at `../sidecar/.venv` (see `../sidecar/README.md`), or set
  `OPENLOCATE_SIDECAR_PYTHON` to a Python interpreter that has `openlocate` installed.
- The Tauri system dependencies for your OS. On Linux that means the WebKitGTK packages listed
  at https://v2.tauri.app/start/prerequisites/ (without them the Tauri crate does not compile).

## Run

```sh
npm install
OPENLOCATE_BACKEND=mock npm run tauri dev
```

## Checks

```sh
npm run typecheck && npm run test && npm run build
cd src-tauri && cargo test && cargo clippy --workspace --all-targets -- -D warnings && cargo fmt --all -- --check
```

`cargo test -p openlocate-sidecar-host` needs no Tauri; it drives the real sidecar if its venv exists.
