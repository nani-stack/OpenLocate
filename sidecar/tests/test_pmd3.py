"""The pymobiledevice3 driver: error translation and device listing, with usbmux faked."""

from __future__ import annotations

import asyncio

import pytest
from pymobiledevice3 import exceptions as pmd
from pymobiledevice3 import usbmux

from openlocate.device import pmd3
from openlocate.device.base import DeviceState
from openlocate.errors import ErrorCode, OpenLocateError


@pytest.mark.parametrize(
    ("exc", "phase", "code"),
    [
        (pmd.ConnectionFailedToUsbmuxdError(), "connect", ErrorCode.DEVICE_SERVICE_UNAVAILABLE),
        (pmd.ConnectionFailedToUsbmuxdError(), "session", ErrorCode.DEVICE_SERVICE_UNAVAILABLE),
        (pmd.PasswordRequiredError(), "connect", ErrorCode.DEVICE_LOCKED),
        (pmd.PasscodeRequiredError("locked", "AAA", "27.2.1"), "mount", ErrorCode.DEVICE_LOCKED),
        (pmd.PairingDialogResponsePendingError(), "connect", ErrorCode.TRUST_REQUIRED),
        (pmd.UserDeniedPairingError(), "connect", ErrorCode.TRUST_REQUIRED),
        (pmd.NotPairedError(), "connect", ErrorCode.TRUST_REQUIRED),
        (pmd.DeveloperModeIsNotEnabledError(), "mount", ErrorCode.DEVELOPER_MODE_OFF),
        (pmd.UserspaceTunnelUnavailableError(), "connect", ErrorCode.IOS_VERSION_UNSUPPORTED),
        (pmd.ConnectionFailedError(), "connect", ErrorCode.DEVICE_NOT_FOUND),
        (pmd.NoDeviceConnectedError(), "connect", ErrorCode.DEVICE_NOT_FOUND),
        (pmd.TSSError(), "mount", ErrorCode.DEVELOPER_IMAGE_FAILED),
        (OSError("no route to host"), "mount", ErrorCode.DEVELOPER_IMAGE_FAILED),
        (pmd.ConnectionTerminatedError(), "session", ErrorCode.DEVICE_DISCONNECTED),
        (ConnectionResetError(), "session", ErrorCode.DEVICE_DISCONNECTED),
        (asyncio.IncompleteReadError(b"", 4), "session", ErrorCode.DEVICE_DISCONNECTED),
        (asyncio.TimeoutError(), "session", ErrorCode.DEVICE_DISCONNECTED),
        (asyncio.TimeoutError(), "connect", ErrorCode.DEVICE_DISCONNECTED),
        (pmd.DvtException("refused"), "session", ErrorCode.INTERNAL),
        (RuntimeError("boom"), "connect", ErrorCode.INTERNAL),
    ],
)
def test_translate(exc: BaseException, phase: pmd3.Phase, code: ErrorCode) -> None:
    error = pmd3.translate(exc, phase)
    assert error.code is code
    assert error.detail is not None and type(exc).__name__ in error.detail


def test_translate_keeps_our_own_errors() -> None:
    ours = OpenLocateError(ErrorCode.DEVELOPER_MODE_OFF)
    assert pmd3.translate(ours, "session") is ours


def fake_usbmux(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    async def list_devices() -> object:
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(usbmux, "list_devices", list_devices)


async def test_a_phone_on_usb_and_wifi_is_listed_once_as_usb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_usbmux(
        monkeypatch,
        [
            usbmux.MuxDevice(1, "AAA", "Network"),
            usbmux.MuxDevice(2, "AAA", "USB"),
            usbmux.MuxDevice(3, "BBB", "Network"),
        ],
    )
    devices = await pmd3._mux_devices()
    assert [(d.serial, d.connection_type) for d in devices] == [("AAA", "USB"), ("BBB", "Network")]


async def test_missing_apple_service_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_usbmux(monkeypatch, pmd.ConnectionFailedToUsbmuxdError())
    driver = pmd3.Pmd3Driver()
    with pytest.raises(OpenLocateError) as caught:
        await driver.discover()
    assert caught.value.code is ErrorCode.DEVICE_SERVICE_UNAVAILABLE
    with pytest.raises(OpenLocateError) as caught:
        await driver.open("AAA")
    assert caught.value.code is ErrorCode.DEVICE_SERVICE_UNAVAILABLE


async def test_no_devices_and_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_usbmux(monkeypatch, [])
    driver = pmd3.Pmd3Driver()
    assert await driver.discover() == []
    with pytest.raises(OpenLocateError) as caught:
        await driver.open("AAA")
    assert caught.value.code is ErrorCode.DEVICE_NOT_FOUND


async def test_a_device_that_cannot_be_described_is_still_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_usbmux(monkeypatch, [usbmux.MuxDevice(1, "AAA", "USB")])

    async def refuse(**_: object) -> None:
        raise pmd.PasswordRequiredError()

    monkeypatch.setattr(pmd3, "create_using_usbmux", refuse)
    (device,) = await pmd3.Pmd3Driver().discover()
    assert (device.id, device.connection, device.state) == ("AAA", "usb", DeviceState.NEEDS_TRUST)
