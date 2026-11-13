"""JSON-RPC 2.0 message parsing and building. No I/O here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openlocate.errors import ErrorCode, OpenLocateError

log = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APPLICATION_ERROR = -32000

JsonObject = dict[str, Any]
RequestId = str | int | float | None


@dataclass(frozen=True)
class Request:
    method: str
    params: JsonObject | list[Any]
    id: RequestId
    is_notification: bool  # True when the message had no "id": no response is sent


class ProtocolError(Exception):
    """A message that cannot be dispatched. Carries what is needed to answer it."""

    def __init__(self, rpc_code: int, error: OpenLocateError, request_id: RequestId = None):
        super().__init__(str(error))
        self.rpc_code = rpc_code
        self.error = error
        self.request_id = request_id


def _reject_constant(name: str) -> Any:
    # json.loads would otherwise accept NaN and Infinity, which are not JSON.
    raise ValueError(f"{name} is not valid JSON")


def _is_valid_id(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return value is None or isinstance(value, (str, int, float))


def parse_request(line: bytes) -> Request:
    """Parse one line into a Request, or raise ProtocolError (-32700 or -32600)."""
    try:
        message = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as err:
        raise ProtocolError(PARSE_ERROR, OpenLocateError(ErrorCode.INTERNAL, str(err))) from err

    if not isinstance(message, dict):
        detail = "batch requests are not supported" if isinstance(message, list) else None
        raise ProtocolError(
            INVALID_REQUEST,
            OpenLocateError(ErrorCode.INTERNAL, detail or "a request must be an object"),
        )

    raw_id = message.get("id")
    request_id: RequestId = raw_id if _is_valid_id(raw_id) else None

    def invalid(detail: str) -> ProtocolError:
        return ProtocolError(
            INVALID_REQUEST, OpenLocateError(ErrorCode.INTERNAL, detail), request_id
        )

    if not _is_valid_id(raw_id):
        raise invalid("id must be a string, a number or null")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise invalid('jsonrpc must be "2.0"')
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise invalid("method must be a non-empty string")
    params = message.get("params", {})
    if not isinstance(params, (dict, list)):
        raise invalid("params must be an object or an array")

    return Request(method=method, params=params, id=request_id, is_notification="id" not in message)


def success_response(request_id: RequestId, result: Any) -> JsonObject:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def error_response(request_id: RequestId, rpc_code: int, error: OpenLocateError) -> JsonObject:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": rpc_code, "message": error.message, "data": error.to_dict()},
    }


def error_from_exception(request_id: RequestId, exc: BaseException) -> JsonObject:
    """Map a handler exception to an error response. Tracebacks stay in the log file."""
    if isinstance(exc, OpenLocateError):
        rpc_code = INVALID_PARAMS if exc.code is ErrorCode.INVALID_PARAMS else APPLICATION_ERROR
        return error_response(request_id, rpc_code, exc)
    log.error("unexpected error while handling a request", exc_info=exc)
    return error_response(request_id, INTERNAL_ERROR, OpenLocateError(ErrorCode.INTERNAL))


def notification(method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}


def encode(message: JsonObject) -> bytes:
    """One compact UTF-8 JSON line, newline included. Raises ValueError/TypeError if the
    message is not representable as strict JSON."""
    text = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return text.encode("utf-8") + b"\n"
