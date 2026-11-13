"""A fake iPhone that records coordinates, so the app can be built without a real phone."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from openlocate.device.base import DeviceBackend, DeviceInfo, DeviceState
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError

log = logging.getLogger(__name__)

MOCK_DEVICE_ID = "MOCK-0001"
HISTORY_LIMIT = 10_000

_MOCK_DEVICE = DeviceInfo(
    id=MOCK_DEVICE_ID,
    name="Mock iPhone",
    model="iPhone (mock)",
    os_version="27.2.1",
    connection="mock",
    state=DeviceState.DISCONNECTED,
)


class MockDevice(DeviceBackend):
    """One fake iPhone.

    fail_connect_with: connect() raises this error code instead of connecting.
    fail_set_after: after this many successful set_location calls, the next one raises
        DEVICE_DISCONNECTED and the device counts as unplugged.
    """

    def __init__(
        self,
        *,
        fail_connect_with: ErrorCode | None = None,
        fail_set_after: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if fail_set_after is not None and fail_set_after < 0:
            raise ValueError("fail_set_after must be >= 0")
        self._fail_connect_with = fail_connect_with
        self._fail_set_after = fail_set_after
        self._clock = clock
        self._connected: DeviceInfo | None = None
        self._successful_sets = 0
        self.current: LatLon | None = None
        self.history: deque[tuple[float, LatLon | None]] = deque(maxlen=HISTORY_LIMIT)

    @property
    def connected(self) -> DeviceInfo | None:
        return self._connected

    async def list_devices(self) -> list[DeviceInfo]:
        log.info("mock: list_devices")
        return [self._connected or _MOCK_DEVICE]

    async def connect(self, device_id: str) -> DeviceInfo:
        log.info("mock: connect %s", device_id)
        if device_id != MOCK_DEVICE_ID:
            raise OpenLocateError(ErrorCode.DEVICE_NOT_FOUND, f"no device with id {device_id!r}")
        if self._fail_connect_with is not None:
            raise OpenLocateError(self._fail_connect_with)
        if self._connected is None:
            self._connected = replace(_MOCK_DEVICE, state=DeviceState.READY)
        return self._connected

    async def disconnect(self) -> None:
        log.info("mock: disconnect")
        self._connected = None

    async def set_location(self, point: LatLon) -> None:
        log.info("mock: set_location %.6f, %.6f", point.lat, point.lon)
        self._require_connected()
        if self._fail_set_after is not None and self._successful_sets >= self._fail_set_after:
            self._connected = None
            raise OpenLocateError(ErrorCode.DEVICE_DISCONNECTED)
        self._successful_sets += 1
        self._record(point)

    async def clear_location(self) -> None:
        log.info("mock: clear_location")
        self._require_connected()
        self._record(None)

    def _require_connected(self) -> None:
        if self._connected is None:
            raise OpenLocateError(ErrorCode.NOT_CONNECTED)

    def _record(self, point: LatLon | None) -> None:
        self.current = point
        self.history.append((self._clock(), point))
