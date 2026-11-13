"""The device interface. The engine, scheduler and RPC layer only ever see this."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from openlocate.engine.geo import LatLon

Connection = Literal["usb", "wifi", "mock"]


class DeviceState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    NEEDS_TRUST = "needs_trust"
    NEEDS_DEVELOPER_MODE = "needs_developer_mode"
    MOUNTING_IMAGE = "mounting_image"
    READY = "ready"
    ERROR = "error"


@dataclass(frozen=True)
class DeviceInfo:
    id: str
    name: str
    model: str
    os_version: str
    connection: Connection
    state: DeviceState


class DeviceBackend(abc.ABC):
    """One way of reaching an iPhone. Controls at most one device at a time.

    Every failure is raised as an OpenLocateError; library exceptions must not escape.
    """

    @property
    @abc.abstractmethod
    def connected(self) -> DeviceInfo | None:
        """The device currently connected, or None."""

    @abc.abstractmethod
    async def list_devices(self) -> list[DeviceInfo]:
        """Devices that can be connected to right now."""

    @abc.abstractmethod
    async def connect(self, device_id: str) -> DeviceInfo:
        """Open a session with the device and return its info in the READY state.

        Raises OpenLocateError(DEVICE_NOT_FOUND) for an unknown id, or another code
        (TRUST_REQUIRED, DEVELOPER_MODE_OFF, ...) when the device is not usable yet.
        Connecting to the device that is already connected returns its info unchanged.
        """

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close the session. Does nothing when nothing is connected."""

    @abc.abstractmethod
    async def set_location(self, point: LatLon) -> None:
        """Make the connected device report `point` as its location.

        Raises OpenLocateError(NOT_CONNECTED) when nothing is connected, and
        OpenLocateError(DEVICE_DISCONNECTED) when the session drops.
        """

    @abc.abstractmethod
    async def clear_location(self) -> None:
        """Return the connected device to its real location.

        Raises OpenLocateError(NOT_CONNECTED) when nothing is connected, and
        OpenLocateError(DEVICE_DISCONNECTED) when the session drops.
        """
