"""RpcServer over a real OS pipe (ThreadedLineReader) and an in-memory writer."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from conftest import TIMEOUT_S, CollectingWriter, PipeInput
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.rpc.protocol import JsonObject
from openlocate.rpc.server import MAX_LINE_BYTES, Handler, Notifier, RpcServer


class FakeHandlers:
    def __init__(self) -> None:
        self.release_slow = asyncio.Event()
        self.shut_down = False
        self.notify: Notifier | None = None
        self.calls: list[str] = []

    def methods(self) -> Mapping[str, Handler]:
        return {
            "echo": self.echo,
            "slow": self.slow,
            "boom": self.boom,
            "fail": self.fail,
            "bad": self.bad,
            "announce": self.announce,
            "nan": self.nan,
        }

    def bind_notifier(self, notify: Notifier) -> None:
        self.notify = notify

    async def shutdown(self) -> None:
        self.shut_down = True

    async def echo(self, params: JsonObject) -> JsonObject:
        self.calls.append("echo")
        return {"echo": params}

    async def slow(self, params: JsonObject) -> JsonObject:
        await self.release_slow.wait()
        return {"slow": True}

    async def boom(self, params: JsonObject) -> JsonObject:
        raise RuntimeError("Traceback secret")

    async def fail(self, params: JsonObject) -> JsonObject:
        raise OpenLocateError(ErrorCode.NOT_CONNECTED)

    async def bad(self, params: JsonObject) -> JsonObject:
        raise OpenLocateError(ErrorCode.INVALID_PARAMS, "x must be a number")

    async def announce(self, params: JsonObject) -> JsonObject:
        assert self.notify is not None
        await self.notify("thing.happened", {"n": 1})
        return {}

    async def nan(self, params: JsonObject) -> JsonObject:
        return {"value": float("nan")}


class Session:
    def __init__(self) -> None:
        self.input = PipeInput()
        self.output = CollectingWriter()
        self.handlers = FakeHandlers()
        self.server = RpcServer(self.input.reader, self.output, self.handlers)
        self.task = asyncio.create_task(self.server.serve())

    async def call(self, request_id: int, method: str, params: Any = None) -> dict[str, Any]:
        await self.input.request(request_id, method, params)
        return await self.output.response(request_id)


@pytest.fixture
async def session() -> AsyncIterator[Session]:
    s = Session()
    yield s
    await s.input.close()
    s.handlers.release_slow.set()
    await asyncio.wait_for(s.task, TIMEOUT_S)


def error_of(response: dict[str, Any]) -> tuple[int, str]:
    return response["error"]["code"], response["error"]["data"]["code"]


async def test_success(session: Session) -> None:
    response = await session.call(1, "echo", {"a": 1})
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {"echo": {"a": 1}}}


async def test_parse_error(session: Session) -> None:
    await session.input.send_raw(b"{oops\n")
    response = await session.output.next_response()
    assert response["id"] is None
    assert error_of(response) == (-32700, "INTERNAL")
    assert response["error"]["data"]["fix"]


async def test_invalid_request(session: Session) -> None:
    await session.input.send({"jsonrpc": "2.0", "id": 9, "method": 5})
    assert error_of(await session.output.response(9)) == (-32600, "INTERNAL")


async def test_unknown_method(session: Session) -> None:
    assert error_of(await session.call(2, "nope")) == (-32601, "INTERNAL")


async def test_positional_params_and_handler_invalid_params(session: Session) -> None:
    assert error_of(await session.call(3, "echo", [1, 2])) == (-32602, "INVALID_PARAMS")
    response = await session.call(4, "bad")
    assert error_of(response) == (-32602, "INVALID_PARAMS")
    assert response["error"]["data"]["detail"] == "x must be a number"


async def test_application_error(session: Session) -> None:
    response = await session.call(5, "fail")
    assert error_of(response) == (-32000, "NOT_CONNECTED")
    assert response["error"]["message"] == "No iPhone is connected."


async def test_internal_error_hides_details(session: Session) -> None:
    response = await session.call(6, "boom")
    assert error_of(response) == (-32603, "INTERNAL")
    assert b"secret" not in b"".join(session.output.lines)


async def test_unencodable_result_becomes_internal(session: Session) -> None:
    assert error_of(await session.call(7, "nan")) == (-32603, "INTERNAL")


async def test_client_notifications_get_no_response(session: Session) -> None:
    await session.input.send({"jsonrpc": "2.0", "method": "echo"})
    await session.input.send({"jsonrpc": "2.0", "method": "boom"})
    await session.input.send_raw(b"\n   \r\n")  # blank lines are ignored
    response = await session.call(8, "echo")
    assert response["id"] == 8
    session.output.drain()
    assert len(session.output.lines) == 1
    assert session.handlers.calls == ["echo", "echo"]


async def test_server_notifications(session: Session) -> None:
    await session.call(10, "announce")
    assert session.output.notifications_named("thing.happened") == [{"n": 1}]


async def test_requests_run_concurrently(session: Session) -> None:
    await session.input.request(11, "slow")
    fast = await session.call(12, "echo")
    assert fast["id"] == 12
    session.output.drain()
    assert len(session.output.lines) == 1  # slow has not answered yet
    session.handlers.release_slow.set()
    assert (await session.output.response(11))["result"] == {"slow": True}


async def test_many_concurrent_requests_keep_lines_whole(session: Session) -> None:
    for i in range(100, 150):
        await session.input.request(i, "announce" if i % 2 else "echo", {})
    for i in range(100, 150):
        assert "result" in await session.output.response(i)
    assert len(session.output.notifications_named("thing.happened")) == 25


async def test_line_over_1_mib_is_rejected_and_the_server_carries_on(session: Session) -> None:
    padding = b" " * MAX_LINE_BYTES
    await session.input.send_raw(b'{"jsonrpc":"2.0","id":20,"method":"echo"}' + padding + b"\n")
    response = await session.output.next_response()
    assert response["id"] is None
    assert error_of(response) == (-32600, "INTERNAL")
    assert (await session.call(21, "echo"))["id"] == 21


async def test_line_of_exactly_1_mib_is_accepted(session: Session) -> None:
    body = b'{"jsonrpc":"2.0","id":22,"method":"echo"}'
    line = body + b" " * (MAX_LINE_BYTES - len(body))
    assert len(line) == MAX_LINE_BYTES
    await session.input.send_raw(line + b"\r\n")
    assert "result" in await session.output.response(22)


async def test_eof_shuts_down_cleanly() -> None:
    s = Session()
    await s.call(1, "echo")
    await s.input.request(2, "slow")
    await s.input.close()
    await asyncio.sleep(0)
    s.handlers.release_slow.set()
    await asyncio.wait_for(s.task, TIMEOUT_S)
    assert s.handlers.shut_down
    assert (await s.output.response(2))["result"] == {"slow": True}  # finished before exit
