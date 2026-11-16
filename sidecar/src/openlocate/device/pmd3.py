"""The pymobiledevice3 driver for the iOS backend. The only module that imports the library.

Written against pymobiledevice3 11.54. Library exceptions are translated here and never
leave this module.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Any, Literal, TypeVar

from packaging.version import InvalidVersion, Version
from pymobiledevice3 import exceptions as pmd
from pymobiledevice3 import usbmux
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.mobile_image_mounter import auto_mount
from pymobiledevice3.services.simulate_location import DtSimulateLocation

from openlocate.device.base import Connection, DeviceInfo, DeviceState
from openlocate.device.ios import IosDriver, IosSession
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError

log = logging.getLogger(__name__)

T = TypeVar("T")
Phase = Literal["connect", "mount", "session"]

# 0 means: show the Trust prompt on the iPhone and fail at once instead of waiting for the tap.
# The user taps Trust and presses Connect again, so no request hangs on a dialog.
PAIR_TIMEOUT_S = 0.0
PROBE_TIMEOUT_S = 8.0
TUNNEL_TIMEOUT_S = 25.0
# The first mount downloads the image and asks Apple's signing server.
MOUNT_TIMEOUT_S = 180.0
COMMAND_TIMEOUT_S = 10.0
CLOSE_TIMEOUT_S = 5.0

_LOCKED = (pmd.PasswordRequiredError, pmd.PasscodeRequiredError)
_UNTRUSTED = (pmd.PairingError, pmd.NotPairedError, pmd.NotTrustedError, pmd.FatalPairingError)
_UNSUPPORTED = (pmd.UserspaceTunnelUnavailableError, pmd.DeviceVersionNotSupportedError)
_GONE = (pmd.NoDeviceConnectedError, pmd.DeviceNotFoundError, pmd.MuxException)
_DROPPED = (pmd.ConnectionTerminatedError, OSError, EOFError, asyncio.TimeoutError)


def translate(exc: BaseException, phase: Phase) -> OpenLocateError:
    """Turn any failure into a catalogued error. `phase` says what was being attempted."""
    if isinstance(exc, OpenLocateError):
        return exc
    detail = f"{type(exc).__name__}: {exc}".rstrip(": ")
    code = _code_for(exc, phase)
    return OpenLocateError(code, detail)


def _code_for(exc: BaseException, phase: Phase) -> ErrorCode:
    # Order matters: several of these classes are subclasses of later ones.
    if isinstance(exc, pmd.ConnectionFailedToUsbmuxdError):
        return ErrorCode.DEVICE_SERVICE_UNAVAILABLE
    if isinstance(exc, _LOCKED):
        return ErrorCode.DEVICE_LOCKED
    if isinstance(exc, _UNTRUSTED):
        return ErrorCode.TRUST_REQUIRED
    if isinstance(exc, pmd.DeveloperModeIsNotEnabledError):
        return ErrorCode.DEVELOPER_MODE_OFF
    if isinstance(exc, _UNSUPPORTED):
        return ErrorCode.IOS_VERSION_UNSUPPORTED
    if phase == "session":
        return ErrorCode.DEVICE_DISCONNECTED if isinstance(exc, _DROPPED) else ErrorCode.INTERNAL
    if phase == "mount":
        return ErrorCode.DEVELOPER_IMAGE_FAILED
    if isinstance(exc, _GONE):
        return ErrorCode.DEVICE_NOT_FOUND
    if isinstance(exc, _DROPPED):
        return ErrorCode.DEVICE_DISCONNECTED
    return ErrorCode.INTERNAL


async def _run(action: Awaitable[T], phase: Phase, timeout: float) -> T:
    """Await a library call with a time limit, translating whatever it raises."""
    try:
        return await asyncio.wait_for(action, timeout)
    except Exception as exc:
        error = translate(exc, phase)
        unexpected = error.code is ErrorCode.INTERNAL
        log.warning("ios: %s step failed: %s", phase, error, exc_info=unexpected)
        raise error from exc


def _major(os_version: str) -> int:
    try:
        return Version(os_version).major
    except InvalidVersion:
        return 0


def _connection(mux: usbmux.MuxDevice) -> Connection:
    return "usb" if mux.is_usb else "wifi"


def _describe(lockdown: Any, mux: usbmux.MuxDevice, state: DeviceState) -> DeviceInfo:
    product_type = lockdown.product_type or "iPhone"
    return DeviceInfo(
        id=mux.serial,
        name=str(lockdown.all_values.get("DeviceName") or "iPhone"),
        model=str(lockdown.display_name or product_type),
        os_version=str(lockdown.product_version),
        connection=_connection(mux),
        state=state,
    )


async def _mux_devices() -> list[usbmux.MuxDevice]:
    """One entry per iPhone. A phone seen over both USB and Wi-Fi is listed as USB."""
    found = await _run(usbmux.list_devices(), "connect", PROBE_TIMEOUT_S)
    by_serial: dict[str, usbmux.MuxDevice] = {}
    for mux in found:
        known = by_serial.get(mux.serial)
        if known is None or (mux.is_usb and not known.is_usb):
            by_serial[mux.serial] = mux
    return list(by_serial.values())


async def _close_quietly(close: Callable[[], Awaitable[object]], what: str) -> None:
    try:
        await asyncio.wait_for(close(), CLOSE_TIMEOUT_S)
    except Exception as exc:  # closing a dead transport routinely fails; nothing to do about it
        log.debug("ios: closing %s failed: %s: %s", what, type(exc).__name__, exc)


class _ConfirmedLocationSimulation(LocationSimulation):
    """Location simulation whose ``clear`` waits for the device to acknowledge it.

    The library sends ``stopLocationSimulation`` without asking for a reply, so the call returns
    as soon as the message is queued, before the device has seen it. Asking for a reply makes
    "reset OK" mean the device answered. iPadOS 27.2 does answer (checked 2026-11-15).
    """

    async def clear(self) -> None:
        await self.service.invoke("stopLocationSimulation", expects_reply=True)


class _Session(IosSession):
    def __init__(
        self,
        info: DeviceInfo,
        location: Any,
        stack: AsyncExitStack,
        is_alive: Callable[[], bool],
    ) -> None:
        self._info = info
        self._location = location
        self._stack = stack
        self._is_alive = is_alive
        self._closed = False

    @property
    def info(self) -> DeviceInfo:
        return self._info

    @property
    def alive(self) -> bool:
        return not self._closed and self._is_alive()

    async def set_location(self, point: LatLon) -> None:
        await _run(self._location.set(point.lat, point.lon), "session", COMMAND_TIMEOUT_S)

    async def clear_location(self) -> None:
        await _run(self._location.clear(), "session", COMMAND_TIMEOUT_S)

    async def close(self) -> None:
        self._closed = True
        try:
            await self._stack.aclose()
        except Exception as exc:
            log.debug("ios: session teardown failed: %s: %s", type(exc).__name__, exc)


class Pmd3Driver(IosDriver):
    async def discover(self) -> list[DeviceInfo]:
        return [await self._probe(mux) for mux in await _mux_devices()]

    async def _probe(self, mux: usbmux.MuxDevice) -> DeviceInfo:
        """Describe a device without pairing: listing must never raise a Trust prompt."""
        connection = _connection(mux)
        unknown = DeviceInfo(mux.serial, "iPhone", "iPhone", "", connection, DeviceState.ERROR)
        try:
            lockdown = await asyncio.wait_for(
                create_using_usbmux(
                    serial=mux.serial, autopair=False, connection_type=mux.connection_type
                ),
                PROBE_TIMEOUT_S,
            )
        except Exception as exc:
            error = translate(exc, "connect")
            log.warning("ios: cannot describe %s: %s", mux.serial, error)
            needs_trust = error.code in (ErrorCode.TRUST_REQUIRED, ErrorCode.DEVICE_LOCKED)
            return replace(unknown, state=DeviceState.NEEDS_TRUST) if needs_trust else unknown
        try:
            state = DeviceState.DISCONNECTED
            if not lockdown.paired:
                state = DeviceState.NEEDS_TRUST
            elif lockdown.has_developer_mode:
                try:
                    enabled = await asyncio.wait_for(
                        lockdown.get_developer_mode_status(), PROBE_TIMEOUT_S
                    )
                except Exception as exc:
                    log.debug("ios: developer mode query failed: %s", exc)
                else:
                    if not enabled:
                        state = DeviceState.NEEDS_DEVELOPER_MODE
            return _describe(lockdown, mux, state)
        finally:
            await _close_quietly(lockdown.close, "probe lockdown")

    async def open(self, device_id: str) -> IosSession:
        mux = next((m for m in await _mux_devices() if m.matches_udid(device_id)), None)
        if mux is None:
            raise OpenLocateError(ErrorCode.DEVICE_NOT_FOUND, f"no device with id {device_id!r}")

        stack = AsyncExitStack()
        try:
            lockdown = await _run(
                create_using_usbmux(
                    serial=mux.serial,
                    autopair=True,
                    pair_timeout=PAIR_TIMEOUT_S,
                    connection_type=mux.connection_type,
                ),
                "connect",
                TUNNEL_TIMEOUT_S,
            )
            stack.push_async_callback(_close_quietly, lockdown.close, "lockdown")
            info = _describe(lockdown, mux, DeviceState.READY)
            await self._require_developer_mode(lockdown)

            if _major(info.os_version) >= 17:
                session = await self._open_rsd(mux, info, stack)
            else:
                session = await self._open_legacy(lockdown, info, stack)
        except BaseException:
            await stack.aclose()
            raise
        return session

    async def _require_developer_mode(self, lockdown: Any) -> None:
        if not lockdown.has_developer_mode:
            return
        if await _run(lockdown.get_developer_mode_status(), "connect", PROBE_TIMEOUT_S):
            return
        # The Developer Mode switch is hidden in Settings until a developer tool asks for it.
        try:
            await asyncio.wait_for(
                AmfiService(lockdown).reveal_developer_mode_option_in_ui(),  # type: ignore[no-untyped-call]
                PROBE_TIMEOUT_S,
            )
        except Exception as exc:
            log.warning("ios: could not reveal the Developer Mode switch: %s", exc)
        raise OpenLocateError(ErrorCode.DEVELOPER_MODE_OFF)

    async def _open_legacy(
        self, lockdown: Any, info: DeviceInfo, stack: AsyncExitStack
    ) -> IosSession:
        """iOS 16 and earlier: plain lockdown, one short connection per command."""
        await self._mount(lockdown)
        return _Session(info, DtSimulateLocation(lockdown), stack, lambda: True)

    async def _open_rsd(
        self, mux: usbmux.MuxDevice, info: DeviceInfo, stack: AsyncExitStack
    ) -> IosSession:
        """iOS 17.4 and later: in-process userspace tunnel, then DVT location simulation."""
        # Imported here: the userspace TCP/IP stack is slow to import and only needed now.
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

        # No RemotePairing fallback: iOS 17.0 to 17.3 is reported as unsupported (see docs).
        tunnel = UserspaceRsdTunnel(serial=mux.serial, autopair=False, remotepairing_fallback=False)
        stack.push_async_callback(_close_quietly, tunnel.aclose, "tunnel")
        rsd = await _run(tunnel.aopen(), "connect", TUNNEL_TIMEOUT_S)
        await self._mount(rsd)

        dvt = DvtProvider(rsd)
        stack.push_async_callback(_close_quietly, dvt.close, "DVT")
        await _run(dvt.connect(), "connect", TUNNEL_TIMEOUT_S)
        location = _ConfirmedLocationSimulation(dvt)
        stack.push_async_callback(_close_quietly, location.close, "location channel")
        await _run(location.connect(), "connect", TUNNEL_TIMEOUT_S)
        # The tunnel clears its `rsd` when the transport dies (for example a pulled cable).
        return _Session(info, location, stack, lambda: tunnel.rsd is not None)

    async def _mount(self, provider: Any) -> None:
        """Make sure the developer disk image is mounted. A reboot unmounts it."""
        try:
            await asyncio.wait_for(auto_mount(provider), MOUNT_TIMEOUT_S)
        except pmd.AlreadyMountedError:
            return
        except Exception as exc:
            error = translate(exc, "mount")
            log.warning("ios: mounting the developer disk image failed: %s", error, exc_info=True)
            raise error from exc
        log.info("ios: developer disk image mounted")
