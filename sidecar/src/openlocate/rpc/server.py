"""Newline-delimited JSON-RPC server over an async line reader and writer."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import BinaryIO, Protocol

from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.rpc.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    JsonObject,
    ProtocolError,
    Request,
    encode,
    error_from_exception,
    error_response,
    notification,
    parse_request,
    success_response,
)

log = logging.getLogger(__name__)

MAX_LINE_BYTES = 1024 * 1024
# Room for the line ending (up to "\r\n") on top of the content limit.
_READ_LIMIT = MAX_LINE_BYTES + 2
_DRAIN_CHUNK = 64 * 1024

Handler = Callable[[JsonObject], Awaitable[JsonObject]]
Notifier = Callable[[str, JsonObject], Awaitable[None]]


class LineReader(Protocol):
    async def readline(self) -> bytes:
        """The next line including its newline, or b"" at end of input.

        A line longer than MAX_LINE_BYTES may be returned cut short, but must still be
        longer than MAX_LINE_BYTES so the server can reject it.
        """
        ...


class LineWriter(Protocol):
    async def write_line(self, line: bytes) -> None: ...


class HandlerSet(Protocol):
    def methods(self) -> Mapping[str, Handler]: ...

    def bind_notifier(self, notify: Notifier) -> None: ...

    async def shutdown(self) -> None: ...


class ThreadedLineReader:
    """Reads lines from a blocking binary stream (such as stdin) in a daemon thread.

    Used on every OS: on Windows the default Proactor event loop cannot reliably attach a
    pipe reader to a console handle. The thread waits for the event loop to accept each
    line, so a fast writer cannot fill memory.
    """

    def __init__(self, stream: BinaryIO, *, queue_size: int = 64) -> None:
        self._stream = stream
        self._queue_size = queue_size
        self._queue: asyncio.Queue[bytes] | None = None
        self._at_eof = False

    async def readline(self) -> bytes:
        if self._at_eof:
            return b""
        if self._queue is None:
            self._queue = asyncio.Queue(self._queue_size)
            thread = threading.Thread(
                target=self._pump,
                args=(asyncio.get_running_loop(), self._queue),
                name="openlocate-stdin",
                daemon=True,
            )
            thread.start()
        line = await self._queue.get()
        if not line:
            self._at_eof = True
        return line

    def _pump(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[bytes]) -> None:
        try:
            while True:
                try:
                    line = self._read_one_line()
                except Exception:
                    log.exception("reading input failed; treating it as end of input")
                    line = b""
                asyncio.run_coroutine_threadsafe(queue.put(line), loop).result()
                if not line:
                    return
        except (RuntimeError, concurrent.futures.CancelledError):
            return  # the event loop has shut down; nobody is listening any more

    def _read_one_line(self) -> bytes:
        line = self._stream.readline(_READ_LIMIT)
        if len(line) >= _READ_LIMIT and not line.endswith(b"\n"):
            # Too long: throw away the rest of it without holding it in memory.
            while True:
                rest = self._stream.readline(_DRAIN_CHUNK)
                if not rest or rest.endswith(b"\n"):
                    break
        return line


class StreamLineWriter:
    """Writes lines to a blocking binary stream (such as stdout) and flushes each one.

    The write runs in a worker thread so a slow reader cannot freeze the event loop.
    """

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    async def write_line(self, line: bytes) -> None:
        await asyncio.to_thread(self._write, line)

    def _write(self, line: bytes) -> None:
        self._stream.write(line)
        self._stream.flush()


class RpcServer:
    """Dispatches each request concurrently; responses and notifications never interleave."""

    def __init__(self, reader: LineReader, writer: LineWriter, handlers: HandlerSet) -> None:
        self._reader = reader
        self._writer = writer
        self._handlers = handlers
        self._methods: dict[str, Handler] = dict(handlers.methods())
        self._write_lock = asyncio.Lock()
        self._in_flight: set[asyncio.Task[None]] = set()
        handlers.bind_notifier(self.notify)

    async def serve(self) -> None:
        """Run until end of input, then finish open requests and shut the handlers down."""
        try:
            while True:
                try:
                    line = await self._reader.readline()
                except OSError:
                    log.exception("reading input failed; shutting down")
                    break
                if not line:
                    log.info("end of input; shutting down")
                    break
                self._handle_line(line)
        finally:
            if self._in_flight:
                await asyncio.gather(*self._in_flight, return_exceptions=True)
            await self._handlers.shutdown()

    async def notify(self, method: str, params: JsonObject) -> None:
        await self._send(notification(method, params))

    def _handle_line(self, line: bytes) -> None:
        content = line.rstrip(b"\r\n")
        if len(content) > MAX_LINE_BYTES:
            error = OpenLocateError(
                ErrorCode.INTERNAL, f"line is longer than {MAX_LINE_BYTES} bytes"
            )
            self._spawn(self._send(error_response(None, INVALID_REQUEST, error)))
            return
        if not content.strip():
            return
        try:
            request = parse_request(content)
        except ProtocolError as err:
            log.warning("rejected a message: %s", err)
            self._spawn(self._send(error_response(err.request_id, err.rpc_code, err.error)))
            return
        self._spawn(self._dispatch(request))

    def _spawn(self, coro: Awaitable[None]) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self._in_flight.add(task)
        task.add_done_callback(self._in_flight.discard)

    async def _dispatch(self, request: Request) -> None:
        response = await self._call(request)
        if request.is_notification:
            if "error" in response:
                log.warning("notification %s failed: %s", request.method, response["error"])
            return
        await self._send(response)

    async def _call(self, request: Request) -> JsonObject:
        handler = self._methods.get(request.method)
        if handler is None:
            error = OpenLocateError(ErrorCode.INTERNAL, f"unknown method {request.method}")
            return error_response(request.id, METHOD_NOT_FOUND, error)
        if not isinstance(request.params, dict):
            error = OpenLocateError(ErrorCode.INVALID_PARAMS, "params must be an object")
            return error_response(request.id, INVALID_PARAMS, error)
        try:
            result = await handler(request.params)
        except Exception as exc:
            return error_from_exception(request.id, exc)
        return success_response(request.id, result)

    async def _send(self, message: JsonObject) -> None:
        try:
            data = encode(message)
        except (TypeError, ValueError) as exc:
            if "id" not in message:
                log.error("could not encode a notification", exc_info=exc)
                return
            data = encode(error_from_exception(message["id"], exc))
        async with self._write_lock:
            try:
                await self._writer.write_line(data)
            except OSError:
                log.exception("could not write to the output stream")
