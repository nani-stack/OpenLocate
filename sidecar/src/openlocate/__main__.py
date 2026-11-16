"""Entry point: python -m openlocate [--backend mock|ios] [--log-dir PATH]

Serves JSON-RPC on stdin/stdout until stdin closes. stdout carries protocol messages only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import BinaryIO

from openlocate import __version__
from openlocate.device.base import DeviceBackend
from openlocate.device.mock import MockDevice
from openlocate.logging_setup import configure_logging
from openlocate.net import RateLimiter
from openlocate.routing.cache import RouteCache, default_cache_dir
from openlocate.routing.osrm import OsrmRouter, servers_from_env
from openlocate.rpc.handlers import SidecarHandlers
from openlocate.rpc.server import RpcServer, StreamLineWriter, ThreadedLineReader
from openlocate.search import NominatimGeocoder, server_from_env

log = logging.getLogger("openlocate")

BACKENDS = ("mock", "ios")
BACKEND_ENV_VAR = "OPENLOCATE_BACKEND"
EXIT_OK = 0
EXIT_STARTUP_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m openlocate",
        description="OpenLocate sidecar: JSON-RPC 2.0 over stdin/stdout.",
    )
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        help=f"device backend (default: ${BACKEND_ENV_VAR}, else ios)",
    )
    parser.add_argument("--log-dir", type=Path, help="directory for the rotating log file")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def _fail(message: str, code: int) -> int:
    print(f"openlocate: {message}", file=sys.stderr)
    return code


def _make_backend(backend_name: str) -> DeviceBackend:
    if backend_name == "mock":
        return MockDevice()
    # Imported here so the mock backend starts without loading pymobiledevice3.
    from openlocate.device.ios import IosDevice
    from openlocate.device.pmd3 import Pmd3Driver

    return IosDevice(Pmd3Driver())


async def _serve(backend_name: str, log_file: Path, stdin: BinaryIO, stdout: BinaryIO) -> None:
    backend = _make_backend(backend_name)
    # One limiter for search and routing together: the public servers allow one request a
    # second for the whole app.
    limiter = RateLimiter(1.0)
    router = OsrmRouter(servers_from_env(), limiter=limiter, cache=RouteCache(default_cache_dir()))
    geocoder = NominatimGeocoder(server_from_env(), limiter=limiter)
    handlers = SidecarHandlers(
        backend, backend_name=backend_name, log_file=log_file, router=router, geocoder=geocoder
    )
    server = RpcServer(ThreadedLineReader(stdin), StreamLineWriter(stdout), handlers)
    log.info("sidecar %s started with the %s backend", __version__, backend_name)
    try:
        await server.serve()
    finally:
        # Closing the session also ends the simulation: the device stops it by itself.
        await backend.disconnect()
    log.info("sidecar stopped")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    backend_name: str = args.backend or os.environ.get(BACKEND_ENV_VAR) or "ios"
    if backend_name not in BACKENDS:
        return _fail(
            f"unknown backend {backend_name!r} in {BACKEND_ENV_VAR}. "
            f"Use one of: {', '.join(BACKENDS)}.",
            EXIT_USAGE,
        )
    if sys.stdin is None or sys.stdout is None:
        return _fail(
            "stdin and stdout must be connected (run it from the app or a terminal).", EXIT_USAGE
        )

    try:
        log_file = configure_logging(args.log_dir)
    except OSError as err:
        return _fail(
            f"cannot create the log file ({err}). Pass a writable folder with --log-dir.",
            EXIT_STARTUP_FAILED,
        )

    protocol_in = sys.stdin.buffer
    protocol_out = sys.stdout.buffer
    # Anything printed by accident must not corrupt the protocol stream.
    sys.stdout = sys.stderr

    try:
        asyncio.run(_serve(backend_name, log_file, protocol_in, protocol_out))
    except KeyboardInterrupt:
        log.info("interrupted")
        return EXIT_INTERRUPTED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
