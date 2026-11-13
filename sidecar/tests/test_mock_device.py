import pytest

from openlocate.device.base import DeviceState
from openlocate.device.mock import HISTORY_LIMIT, MOCK_DEVICE_ID, MockDevice
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError

POINT = LatLon(48.85, 2.35)


async def test_list_connect_set_clear_disconnect() -> None:
    device = MockDevice(clock=lambda: 5.0)
    [listed] = await device.list_devices()
    assert listed.id == MOCK_DEVICE_ID
    assert listed.name == "Mock iPhone"
    assert listed.os_version == "27.2.1"
    assert listed.state is DeviceState.DISCONNECTED
    assert device.connected is None

    info = await device.connect(MOCK_DEVICE_ID)
    assert info.state is DeviceState.READY
    assert device.connected == info
    assert await device.connect(MOCK_DEVICE_ID) == info

    await device.set_location(POINT)
    await device.clear_location()
    assert device.current is None
    assert list(device.history) == [(5.0, POINT), (5.0, None)]

    await device.disconnect()
    assert device.connected is None


async def test_set_and_clear_need_a_connection() -> None:
    device = MockDevice()
    for call in (device.set_location(POINT), device.clear_location()):
        with pytest.raises(OpenLocateError) as info:
            await call
        assert info.value.code is ErrorCode.NOT_CONNECTED


async def test_unknown_device_id() -> None:
    with pytest.raises(OpenLocateError) as info:
        await MockDevice().connect("NOPE")
    assert info.value.code is ErrorCode.DEVICE_NOT_FOUND


async def test_fail_connect_with() -> None:
    device = MockDevice(fail_connect_with=ErrorCode.DEVELOPER_MODE_OFF)
    with pytest.raises(OpenLocateError) as info:
        await device.connect(MOCK_DEVICE_ID)
    assert info.value.code is ErrorCode.DEVELOPER_MODE_OFF
    assert device.connected is None


async def test_fail_set_after() -> None:
    device = MockDevice(fail_set_after=2)
    await device.connect(MOCK_DEVICE_ID)
    await device.set_location(POINT)
    await device.set_location(POINT)
    with pytest.raises(OpenLocateError) as info:
        await device.set_location(POINT)
    assert info.value.code is ErrorCode.DEVICE_DISCONNECTED
    assert device.connected is None


async def test_history_is_bounded() -> None:
    device = MockDevice()
    await device.connect(MOCK_DEVICE_ID)
    for _ in range(HISTORY_LIMIT + 5):
        await device.set_location(POINT)
    assert len(device.history) == HISTORY_LIMIT
