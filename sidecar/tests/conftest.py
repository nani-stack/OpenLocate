"""Shared test helpers. Nothing here sleeps for real: fake time only yields to the loop."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from openlocate.device.mock import MockDevice
from openlocate.rpc.handlers import SidecarHandlers
from openlocate.rpc.server import RpcServer, ThreadedLineReader

# A generous guard for steps that cross a thread boundary. Never reached when things work.
TIMEOUT_S = 5.0


async def settle(rounds: int = 50) -> None:
    """Let every ready task run until things quiet down (no real sleeping)."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeTime:
    """An injectable clock and sleep. Time moves only when a test calls advance()."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self._sleepers: list[asyncio.Future[None]] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._sleepers.append(future)
        await future

    @property
    def sleepers(self) -> int:
        return sum(1 for f in self._sleepers if not f.done())

    async def advance(self, seconds: float) -> None:
        """Move the clock forward and wake everything that was sleeping."""
        self.now += seconds
        sleepers, self._sleepers = self._sleepers, []
        for future in sleepers:
            if not future.done():
                future.set_result(None)
        await settle()

    async def ticks(self, count: int, seconds: float = 1.0) -> None:
        for _ in range(count):
            await self.advance(seconds)


class PipeInput:
    """Feeds a ThreadedLineReader through a real OS pipe, like stdin in production."""

    def __init__(self) -> None:
        read_fd, write_fd = os.pipe()
        self.reader = ThreadedLineReader(os.fdopen(read_fd, "rb"))
        self._write_end = os.fdopen(write_fd, "wb")

    async def send_raw(self, data: bytes) -> None:
        await asyncio.to_thread(self._write, data)

    async def send(self, message: Any) -> None:
        await self.send_raw(json.dumps(message).encode("utf-8") + b"\n")

    async def request(self, request_id: int, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        await self.send(message)

    async def close(self) -> None:
        if not self._write_end.closed:
            await asyncio.to_thread(self._write_end.close)

    def _write(self, data: bytes) -> None:
        self._write_end.write(data)
        self._write_end.flush()


class CollectingWriter:
    """An in-memory LineWriter that parses what the server writes."""

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.notifications: list[dict[str, Any]] = []
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._responses: dict[Any, dict[str, Any]] = {}

    async def write_line(self, line: bytes) -> None:
        assert line.endswith(b"\n") and line.count(b"\n") == 1
        self.lines.append(line)
        self._queue.put_nowait(json.loads(line))

    async def _next(self) -> dict[str, Any]:
        message = await asyncio.wait_for(self._queue.get(), TIMEOUT_S)
        if "method" in message:
            self.notifications.append(message)
        else:
            self._responses[message["id"]] = message
        return message

    async def response(self, request_id: Any) -> dict[str, Any]:
        while request_id not in self._responses:
            await self._next()
        return self._responses.pop(request_id)

    async def next_response(self) -> dict[str, Any]:
        while True:
            message = await self._next()
            if "method" not in message:
                self._responses.pop(message["id"], None)
                return message

    def drain(self) -> None:
        """Move everything already written into notifications / responses."""
        while not self._queue.empty():
            message = self._queue.get_nowait()
            if "method" in message:
                self.notifications.append(message)
            else:
                self._responses[message["id"]] = message

    def notifications_named(self, method: str) -> list[dict[str, Any]]:
        self.drain()
        return [n["params"] for n in self.notifications if n["method"] == method]


class Sidecar:
    """The real handlers and server, driven over a pipe, with fake time."""

    def __init__(self, device: MockDevice) -> None:
        self.device = device
        self.time = FakeTime()
        self.handlers = SidecarHandlers(
            device,
            backend_name="mock",
            log_file=Path("sidecar.log"),
            clock=self.time.clock,
            sleep=self.time.sleep,
        )
        self.input = PipeInput()
        self.output = CollectingWriter()
        self.server = RpcServer(self.input.reader, self.output, self.handlers)
        self.task = asyncio.create_task(self.server.serve())
        self._next_id = 0

    async def call(self, method: str, params: Any = None) -> dict[str, Any]:
        self._next_id += 1
        await self.input.request(self._next_id, method, params)
        return await self.output.response(self._next_id)

    async def result(self, method: str, params: Any = None) -> Any:
        response = await self.call(method, params)
        assert "result" in response, response
        return response["result"]

    async def error(self, method: str, params: Any = None) -> tuple[int, str]:
        response = await self.call(method, params)
        assert "error" in response, response
        return response["error"]["code"], response["error"]["data"]["code"]

    async def close(self) -> None:
        await self.input.close()
        await asyncio.wait_for(self.task, TIMEOUT_S)
