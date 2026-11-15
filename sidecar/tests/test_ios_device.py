"""The iOS backend's session rules, with a fake driver (no phone, no pymobiledevice3)."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import replace

import pytest

from openlocate.device.base import DeviceInfo, DeviceState
from openlocate.device.ios import IosDevice, IosDriver, IosSession
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError

PHONE = DeviceInfo("UDID-1", "My iPhone", "iPhone 15", "27.2.1", "usb", DeviceState.DISCONNECTED)
OTHER = replace(PHONE, id="UDID-2", name="Other iPhone")
PARIS = LatLon(48.8584, 2.2945)


class FakeSession(IosSession):
    def __init__(self, info: DeviceInfo) -> None:
        self._info = replace(info, state=DeviceState.READY)
        self.is_alive = True
        self.closed = 0
        self.sent: list[LatLon | None] = []
        self.fail_with: ErrorCode | None = None

    @property
    def info(self) -> DeviceInfo:
        return self._info

    @property
    def alive(self) -> bool:
        return self.is_alive

    async def set_location(self, point: LatLon) -> None:
        self._send(point)

    async def clear_location(self) -> None:
        self._send(None)

    async def close(self) -> None:
        self.closed += 1
        self.is_alive = False

    def _send(self, point: LatLon | None) -> None:
        if self.fail_with is not None:
            raise OpenLocateError(self.fail_with)
        self.sent.append(point)


class FakeDriver(IosDriver):
    def __init__(self, *devices: DeviceInfo) -> None:
        self.devices = list(devices)
        self.sessions: list[FakeSession] = []
        self.fail_open_with: ErrorCode | None = None

    async def discover(self) -> list[DeviceInfo]:
        return list(self.devices)

    async def open(self, device_id: str) -> IosSession:
        if self.fail_open_with is not None:
            raise OpenLocateError(self.fail_open_with)
        info = next((d for d in self.devices if d.id == device_id), None)
        if info is None:
            raise OpenLocateError(ErrorCode.DEVICE_NOT_FOUND)
        self.sessions.append(FakeSession(info))
        return self.sessions[-1]


async def raises(code: ErrorCode, awaitable: Awaitable[object]) -> None:
    with pytest.raises(OpenLocateError) as caught:
        await awaitable
    assert caught.value.code is code


async def test_connect_set_clear_disconnect() -> None:
    driver = FakeDriver(PHONE)
    device = IosDevice(driver)
    assert device.connected is None

    info = await device.connect(PHONE.id)
    assert info.state is DeviceState.READY
    assert device.connected == info

    await device.set_location(PARIS)
    await device.clear_location()
    assert driver.sessions[0].sent == [PARIS, None]

    await device.disconnect()
    assert device.connected is None
    assert driver.sessions[0].closed == 1
    await device.disconnect()  # nothing connected: does nothing


async def test_location_calls_need_a_connection() -> None:
    device = IosDevice(FakeDriver(PHONE))
    await raises(ErrorCode.NOT_CONNECTED, device.set_location(PARIS))
    await raises(ErrorCode.NOT_CONNECTED, device.clear_location())


async def test_connecting_twice_reuses_the_session() -> None:
    driver = FakeDriver(PHONE)
    device = IosDevice(driver)
    first = await device.connect(PHONE.id)
    assert await device.connect(PHONE.id) == first
    assert len(driver.sessions) == 1


async def test_connecting_to_another_device_closes_the_first() -> None:
    driver = FakeDriver(PHONE, OTHER)
    device = IosDevice(driver)
    await device.connect(PHONE.id)
    info = await device.connect(OTHER.id)
    assert info.id == OTHER.id
    assert driver.sessions[0].closed == 1
    assert device.connected == info


async def test_failed_connect_leaves_nothing_connected() -> None:
    driver = FakeDriver(PHONE)
    driver.fail_open_with = ErrorCode.DEVELOPER_MODE_OFF
    device = IosDevice(driver)
    await raises(ErrorCode.DEVELOPER_MODE_OFF, device.connect(PHONE.id))
    assert device.connected is None
    await raises(ErrorCode.DEVICE_NOT_FOUND, IosDevice(FakeDriver()).connect("nope"))


async def test_list_shows_the_connected_device_as_ready() -> None:
    driver = FakeDriver(PHONE, OTHER)
    device = IosDevice(driver)
    assert [d.state for d in await device.list_devices()] == [DeviceState.DISCONNECTED] * 2
    await device.connect(OTHER.id)
    states = {d.id: d.state for d in await device.list_devices()}
    assert states == {PHONE.id: DeviceState.DISCONNECTED, OTHER.id: DeviceState.READY}


async def test_a_dead_session_is_reported_and_dropped() -> None:
    driver = FakeDriver(PHONE)
    device = IosDevice(driver)
    await device.connect(PHONE.id)
    driver.sessions[0].is_alive = False  # the cable was pulled

    assert device.connected is None
    await raises(ErrorCode.DEVICE_DISCONNECTED, device.set_location(PARIS))
    assert driver.sessions[0].closed == 1
    await raises(ErrorCode.NOT_CONNECTED, device.set_location(PARIS))

    await device.connect(PHONE.id)  # reconnecting opens a new session
    assert len(driver.sessions) == 2
    await device.set_location(PARIS)


async def test_a_disconnect_error_during_a_command_drops_the_session() -> None:
    driver = FakeDriver(PHONE)
    device = IosDevice(driver)
    await device.connect(PHONE.id)
    driver.sessions[0].fail_with = ErrorCode.DEVICE_DISCONNECTED
    await raises(ErrorCode.DEVICE_DISCONNECTED, device.set_location(PARIS))
    assert device.connected is None
    assert driver.sessions[0].closed == 1


async def test_other_errors_keep_the_session() -> None:
    driver = FakeDriver(PHONE)
    device = IosDevice(driver)
    await device.connect(PHONE.id)
    driver.sessions[0].fail_with = ErrorCode.INTERNAL
    await raises(ErrorCode.INTERNAL, device.clear_location())
    assert device.connected is not None
    assert driver.sessions[0].closed == 0
