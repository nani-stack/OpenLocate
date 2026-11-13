"""Device backends behind one interface."""

from openlocate.device.base import Connection, DeviceBackend, DeviceInfo, DeviceState
from openlocate.device.mock import MOCK_DEVICE_ID, MockDevice

__all__ = [
    "MOCK_DEVICE_ID",
    "Connection",
    "DeviceBackend",
    "DeviceInfo",
    "DeviceState",
    "MockDevice",
]
