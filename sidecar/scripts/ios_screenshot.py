"""Developer tool: open Maps on a connected iPhone or iPad, centre it, and save a screenshot.

Used to check location tests without looking at the device. It opens its own short session,
so it can run while the sidecar is connected. Needs iOS 17.4 or later, a USB cable, Developer
Mode on, and the device unlocked.

    .venv/Scripts/python.exe scripts/ios_screenshot.py shot.png
    .venv/Scripts/python.exe scripts/ios_screenshot.py shot.png --max-size 1100
    .venv/Scripts/python.exe scripts/ios_screenshot.py shot.png --no-launch --no-locate

What to read in the picture:
- The dot. Blue is a live position, grey is the last known one, none means no position.
- The status bar clock. It follows the time zone of the simulated place.

Maps reopens on the area it showed last, not on the dot, so the script taps the locate button
(top right). `--locate-at` moves that tap if the button is elsewhere, as fractions of the
screenshot from its top left. Taps are sent in the screen's upright (portrait) frame; pass
`--flip` if the device is held in the other landscape direction and the tap misses.

The same steps with the library's own commands:

    python -m pymobiledevice3 developer dvt launch com.apple.Maps
    python -m pymobiledevice3 developer core-device universal-hid-service tap X Y
    python -m pymobiledevice3 developer dvt screenshot shot.png
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

from pymobiledevice3 import usbmux
from pymobiledevice3.remote.core_device.hid_service import (
    TOUCHSCREEN_STATE_CONTACT,
    TOUCHSCREEN_STATE_RELEASE,
    touch_session,
)
from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot

MAPS = "com.apple.Maps"
LOCATE_BUTTON = (0.965, 0.145)  # Maps on iPadOS 27, landscape: the arrow under the map button
HID_MAX = 65535


async def _first_usb_udid() -> str:
    for device in await usbmux.list_devices():
        if device.is_usb:
            return str(device.serial)
    raise SystemExit("No iPhone or iPad found on USB. Plug it in and unlock it.")


def to_touch_frame(point: tuple[float, float], landscape: bool, flip: bool) -> tuple[int, int]:
    """Turn a point on the screenshot (fractions) into touchscreen units (upright frame)."""
    x, y = point
    if landscape:
        x, y = (y, 1 - x) if flip else (1 - y, x)
    elif flip:
        x, y = 1 - x, 1 - y
    return round(x * HID_MAX), round(y * HID_MAX)


async def _tap(rsd: object, point: tuple[float, float], landscape: bool, flip: bool) -> None:
    x, y = to_touch_frame(point, landscape, flip)
    async with touch_session(rsd) as hid:  # type: ignore[arg-type]
        service_id = await hid.active_touchscreen_service_id()
        await hid.send_touchscreen(TOUCHSCREEN_STATE_CONTACT, x, y, service_id=service_id)
        await asyncio.sleep(0.05)
        await hid.send_touchscreen(TOUCHSCREEN_STATE_RELEASE, x, y, service_id=service_id)


def _is_landscape(png: bytes) -> bool:
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    return width > height


def _shrink(png: bytes, max_size: int) -> bytes:
    from PIL import Image  # installed with pymobiledevice3

    image = Image.open(io.BytesIO(png))
    image.thumbnail((max_size, max_size))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def capture(args: argparse.Namespace) -> None:
    udid = args.udid or await _first_usb_udid()
    tunnel = UserspaceRsdTunnel(serial=udid, autopair=False, remotepairing_fallback=False)
    async with tunnel as rsd, DvtProvider(rsd) as dvt, Screenshot(dvt) as screenshot:
        if not args.no_launch:
            async with ProcessControl(dvt) as control:
                pid = await control.launch(bundle_id=args.app, kill_existing=not args.keep)
            print(f"opened {args.app} (pid {pid})", file=sys.stderr)
            await asyncio.sleep(args.wait)
        if not args.no_locate:
            landscape = _is_landscape(await screenshot.get_screenshot())
            await _tap(rsd, args.locate_at, landscape, args.flip)
            await asyncio.sleep(args.settle)
        data = await screenshot.get_screenshot()
    if args.max_size:
        data = _shrink(data, args.max_size)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(args.out.resolve())


def _point(text: str) -> tuple[float, float]:
    x, y = (float(part) for part in text.split(","))
    return x, y


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("out", type=Path, help="PNG file to write")
    parser.add_argument("--udid", help="device id (default: the first device on USB)")
    parser.add_argument("--app", default=MAPS, help=f"bundle id to open (default: {MAPS})")
    parser.add_argument("--no-launch", action="store_true", help="do not open the app first")
    parser.add_argument("--keep", action="store_true", help="do not restart the app if it runs")
    parser.add_argument("--wait", type=float, default=4.0, help="seconds to wait after opening")
    parser.add_argument("--no-locate", action="store_true", help="do not tap the locate button")
    parser.add_argument("--locate-at", type=_point, default=LOCATE_BUTTON, metavar="X,Y")
    parser.add_argument("--flip", action="store_true", help="device is turned the other way")
    parser.add_argument("--settle", type=float, default=4.0, help="seconds to wait after the tap")
    parser.add_argument("--max-size", type=int, default=0, help="shrink the longer side to this")
    asyncio.run(capture(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
