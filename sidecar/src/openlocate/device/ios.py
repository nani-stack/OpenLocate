"""The real-iPhone backend: session bookkeeping on top of a driver.

This module holds no pymobiledevice3 code, so its rules (one device at a time, what happens
when the session drops) are tested without a phone. The library calls live in `pmd3.py`.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Awaitable

from openlocate.device.base import DeviceBackend, DeviceInfo
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError

log = logging.getLogger(__name__)


class IosSession(abc.ABC):
    """An open developer session with one iPhone. Failures are raised as OpenLocateError."""

    @property
    @abc.abstractmethod
    def info(self) -> DeviceInfo:
        """The device, in the READY state."""

    @property
    @abc.abstractmethod
    def alive(self) -> bool:
        """False once the transport is known to be gone (for example the cable was pulled)."""

    @abc.abstractmethod
    async def set_location(self, point: LatLon) -> None: ...

    @abc.abstractmethod
    async def clear_location(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Release everything. Must not raise."""


class IosDriver(abc.ABC):
    """Finds iPhones and opens sessions. Failures are raised as OpenLocateError."""

    @abc.abstractmethod
    async def discover(self) -> list[DeviceInfo]: ...

    @abc.abstractmethod
    async def open(self, device_id: str) -> IosSession: ...


class IosDevice(DeviceBackend):
    """Owns at most one long-lived session.

    The session is kept until disconnect() or until it drops, so each location change costs
    one message. The simulation lives only as long as the session: when it closes, the device
    stops simulating by itself (seen in the locationd log on iPadOS 27.2). Apps may keep showing
    the last simulated position until the device gets a real fix again.
    """

    def __init__(self, driver: IosDriver) -> None:
        self._driver = driver
        self._session: IosSession | None = None
        # Serialises everything that touches the session: connect, disconnect, set, clear.
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> DeviceInfo | None:
        session = self._session
        return session.info if session is not None and session.alive else None

    async def list_devices(self) -> list[DeviceInfo]:
        devices = await self._driver.discover()
        current = self.connected
        if current is None:
            return devices
        return [current if device.id == current.id else device for device in devices]

    async def connect(self, device_id: str) -> DeviceInfo:
        async with self._lock:
            session = self._session
            if session is not None and session.alive and session.info.id == device_id:
                return session.info
            await self._drop()
            log.info("ios: connecting to %s", device_id)
            self._session = await self._driver.open(device_id)
            info = self._session.info
            log.info("ios: connected to %s (iOS %s, %s)", info.id, info.os_version, info.connection)
            return info

    async def disconnect(self) -> None:
        async with self._lock:
            await self._drop()

    async def set_location(self, point: LatLon) -> None:
        async with self._lock:
            session = await self._require_session()
            log.info("ios: set_location %.6f, %.6f", point.lat, point.lon)
            await self._guard(session.set_location(point))

    async def clear_location(self) -> None:
        async with self._lock:
            session = await self._require_session()
            log.info("ios: clear_location")
            await self._guard(session.clear_location())

    async def _require_session(self) -> IosSession:
        session = self._session
        if session is None:
            raise OpenLocateError(ErrorCode.NOT_CONNECTED)
        if not session.alive:
            await self._drop()
            raise OpenLocateError(ErrorCode.DEVICE_DISCONNECTED)
        return session

    async def _guard(self, action: Awaitable[None]) -> None:
        try:
            await action
        except OpenLocateError as err:
            if err.code is ErrorCode.DEVICE_DISCONNECTED:
                await self._drop()
            raise

    async def _drop(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            log.info("ios: closing the session with %s", session.info.id)
            await session.close()
