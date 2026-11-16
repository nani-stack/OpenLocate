# OpenLocate sidecar

The Python process that holds OpenLocate's logic: the route engine, device backends and a
JSON-RPC 2.0 server that talks to the desktop app over stdin/stdout (one JSON object per line).

Set up a virtualenv (Python 3.10 or newer) from this `sidecar/` folder:

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"        # Windows: .venv\Scripts\pip install -e ".[dev]"

Run the checks:

    .venv/bin/python -m pytest -q
    .venv/bin/ruff check .
    .venv/bin/mypy src

The checks need no iPhone: the iOS backend is tested with a fake driver and a faked usbmux.

Run the sidecar with the fake phone and type requests by hand (Ctrl+D, or Ctrl+Z then Enter
on Windows, closes stdin and exits):

    .venv/bin/python -m openlocate --backend mock
    {"jsonrpc": "2.0", "id": 1, "method": "app.info"}

Without `--backend mock` the sidecar uses the real iPhone backend (`--backend ios`). On Windows
that needs the Apple Devices app (or iTunes) for Apple's USB service.

Load a route that follows real roads (this contacts the routing server, see the main README):

    {"jsonrpc": "2.0", "id": 2, "method": "playback.loadRoute", "params": {"waypoints": [[48.8584, 2.2945], [48.8738, 2.2950]], "profile": "walk"}}

Logs go to a rotating file (see `logFile` in the `app.info` reply) and to stderr, never stdout.
