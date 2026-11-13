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

Run the sidecar with the fake phone and type requests by hand (Ctrl+D, or Ctrl+Z then Enter
on Windows, closes stdin and exits):

    .venv/bin/python -m openlocate --backend mock
    {"jsonrpc": "2.0", "id": 1, "method": "app.info"}

Logs go to a rotating file (see `logFile` in the `app.info` reply) and to stderr, never stdout.
