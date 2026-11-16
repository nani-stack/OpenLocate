"""Stand-in for pytun_pmd3 in the standalone helper.

The real package creates a kernel network adapter (on Windows through wintun.dll, a driver
library with its own proprietary licence) and needs administrator rights. OpenLocate never
does that: it reaches the device through pymobiledevice3's in-process tunnel. The device
library still imports the name, so the helper ships this stand-in instead of the driver.
"""


class TunTapDevice:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "This build of OpenLocate does not include the kernel network adapter. "
            "It uses the in-process tunnel only."
        )
