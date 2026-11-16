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
    DEVICE_LOCKED = "DEVICE_LOCKED"
    DEVICE_SERVICE_UNAVAILABLE = "DEVICE_SERVICE_UNAVAILABLE"
    IOS_VERSION_UNSUPPORTED = "IOS_VERSION_UNSUPPORTED"
    DEVELOPER_IMAGE_FAILED = "DEVELOPER_IMAGE_FAILED"
    INVALID_PARAMS = "INVALID_PARAMS"
    INVALID_STATE = "INVALID_STATE"
    NO_ROUTE_LOADED = "NO_ROUTE_LOADED"
    NO_ROUTE_FOUND = "NO_ROUTE_FOUND"
    ROUTING_UNAVAILABLE = "ROUTING_UNAVAILABLE"
    SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"
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
    ErrorCode.DEVICE_LOCKED: ErrorInfo(
        "The iPhone is locked.",
        "Unlock the iPhone with its passcode, keep it unlocked, then connect again.",
    ),
    ErrorCode.DEVICE_SERVICE_UNAVAILABLE: ErrorInfo(
        "Apple's device service is not running on this computer.",
        "On Windows, install the Apple Devices app from the Microsoft Store (or iTunes), open "
        "it, plug the iPhone in with a USB cable, then refresh the device list.",
    ),
    ErrorCode.IOS_VERSION_UNSUPPORTED: ErrorInfo(
        "This iOS version is not supported.",
        "iOS 17.0 to 17.3 cannot be used. Update the iPhone to iOS 17.4 or later in "
        "Settings → General → Software Update, then connect again.",
    ),
    ErrorCode.DEVELOPER_IMAGE_FAILED: ErrorInfo(
        "The developer disk image could not be set up on the iPhone.",
        "Check that this computer is online (the image is downloaded and signed by Apple the "
        "first time), keep the iPhone unlocked, then connect again. If Xcode is open, close it.",
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
    ErrorCode.NO_ROUTE_FOUND: ErrorInfo(
        "No route could be found between those places.",
        "Move the points closer to a road or path, or pick another way of travelling "
        "(walking, cycling or driving), then try again.",
    ),
    ErrorCode.ROUTING_UNAVAILABLE: ErrorInfo(
        "The routing service could not be reached.",
        "Check that this computer is online and try again in a minute. The free routing "
        "service has no uptime promise.",
    ),
    ErrorCode.SEARCH_UNAVAILABLE: ErrorInfo(
        "The address search could not be reached.",
        "Check that this computer is online and try again in a minute. You can also enter "
        "coordinates instead of an address.",
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
