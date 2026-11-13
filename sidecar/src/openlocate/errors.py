"""The single catalogue of errors the sidecar can report.

Every failure that reaches the UI carries a stable code, a plain-language message and a
suggested fix. Library exceptions are translated into these at the backend boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

_REPORT_BUG = (
    "This is a bug in OpenLocate. Restart the app, and if it happens again report it with "
    "the log file attached (review the log first: it contains coordinates)."
)


class ErrorCode(str, Enum):
    """Stable error codes. The string value is what goes over the wire."""

    NOT_CONNECTED = "NOT_CONNECTED"
    DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
    DEVICE_DISCONNECTED = "DEVICE_DISCONNECTED"
    TRUST_REQUIRED = "TRUST_REQUIRED"
    DEVELOPER_MODE_OFF = "DEVELOPER_MODE_OFF"
    INVALID_PARAMS = "INVALID_PARAMS"
    INVALID_STATE = "INVALID_STATE"
    NO_ROUTE_LOADED = "NO_ROUTE_LOADED"
    # Also used for protocol-level failures (unreadable message, unknown method): from the
    # user's point of view those are bugs in OpenLocate. The JSON-RPC error code and the
    # detail tell developers which one it was.
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class ErrorInfo:
    message: str
    fix: str


CATALOGUE: Mapping[ErrorCode, ErrorInfo] = {
    ErrorCode.NOT_CONNECTED: ErrorInfo(
        "No iPhone is connected.",
        "Connect an iPhone, select it in the device list, then try again.",
    ),
    ErrorCode.DEVICE_NOT_FOUND: ErrorInfo(
        "That iPhone could not be found.",
        "Check the USB cable (or that the iPhone is on the same Wi-Fi), unlock the iPhone, "
        "then refresh the device list.",
    ),
    ErrorCode.DEVICE_DISCONNECTED: ErrorInfo(
        "The connection to the iPhone was lost.",
        "Reconnect the cable (or bring the iPhone back onto the same Wi-Fi), unlock it, "
        "then connect again.",
    ),
    ErrorCode.TRUST_REQUIRED: ErrorInfo(
        "The iPhone does not trust this computer yet.",
        "Unlock the iPhone, tap Trust on the “Trust This Computer?” prompt and enter "
        "your passcode, then connect again.",
    ),
    ErrorCode.DEVELOPER_MODE_OFF: ErrorInfo(
        "Developer Mode is turned off on the iPhone.",
        "On the iPhone open Settings → Privacy & Security → Developer Mode, turn it on, "
        "then restart when asked.",
    ),
    ErrorCode.INVALID_PARAMS: ErrorInfo(
        "The request had missing or invalid values.",
        "Check the values you entered and try again. If this keeps happening, report it with "
        "the log file attached.",
    ),
    ErrorCode.INVALID_STATE: ErrorInfo(
        "That action is not possible right now.",
        "Check the current playback state (for example, resume only works while paused) and "
        "try again.",
    ),
    ErrorCode.NO_ROUTE_LOADED: ErrorInfo(
        "No route is loaded.",
        "Load a route first, then start playback.",
    ),
    ErrorCode.INTERNAL: ErrorInfo(
        "Something went wrong inside OpenLocate.",
        "Try again. " + _REPORT_BUG,
    ),
}


class OpenLocateError(Exception):
    """An error with a catalogue entry, safe to show to the user."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        info = CATALOGUE[code]
        self.code = code
        self.message = info.message
        self.fix = info.fix
        self.detail = detail
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"{code.value}: {info.message}{suffix}")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code.value,
            "message": self.message,
            "fix": self.fix,
            "detail": self.detail,
        }
