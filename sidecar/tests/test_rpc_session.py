"""A full session: SidecarHandlers + MockDevice + RpcServer over in-memory streams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from conftest import Sidecar, settle
from openlocate import __version__
from openlocate.device.mock import MOCK_DEVICE_ID, MockDevice
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.rpc.handlers import MAX_ROUTE_POINTS, SidecarHandlers

# Two points about 1112 m apart on the equator.
ROUTE = [[0.0, 0.0], [0.0, 0.01]]
SPEED_KMH = 360.0  # 100 m/s, so one tick is 100 m


@pytest.fixture
async def sidecar() -> AsyncIterator[Sidecar]:
    s = Sidecar(MockDevice())
    yield s
    await s.close()


async def test_full_session(sidecar: Sidecar) -> None:
    info = await sidecar.result("app.info")
    assert info == {"version": __version__, "backend": "mock", "logFile": "sidecar.log"}

    devices = (await sidecar.result("device.list"))["devices"]
    assert devices[0]["id"] == MOCK_DEVICE_ID
    assert devices[0]["osVersion"] == "27.2.1"
    assert devices[0]["state"] == "disconnected"

    connected = await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
    assert connected["state"] == "ready"
    assert connected["connection"] == "mock"

    assert await sidecar.result("location.set", {"lat": 48.8566, "lon": 2.3522}) == {}
    assert sidecar.output.notifications_named("location.updated") == [
        {"lat": 48.8566, "lon": 2.3522, "source": "teleport"}
    ]

    loaded = await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": SPEED_KMH})
    assert loaded["points"] == 2
    assert loaded["lengthM"] == pytest.approx(1111.95, abs=0.01)

    status = await sidecar.result("playback.start")
    assert status["state"] == "playing"
    assert status["speedKmh"] == pytest.approx(SPEED_KMH)
    await settle()
    await sidecar.time.ticks(3)

    status = await sidecar.result("playback.status")
    assert set(status) == {
        "state",
        "distanceM",
        "lengthM",
        "progress",
        "speedKmh",
        "lap",
        "position",
    }
    assert status["distanceM"] == pytest.approx(300.0)
    assert status["position"]["lat"] == pytest.approx(0.0)

    paused = await sidecar.result("playback.pause")
    assert paused["state"] == "paused"
    resumed = await sidecar.result("playback.resume")
    assert resumed["state"] == "playing"
    slower = await sidecar.result("playback.setSpeed", {"speedKmh": 180})
    assert slower["speedKmh"] == pytest.approx(180.0)

    stopped = await sidecar.result("playback.stop")
    assert stopped["state"] == "idle"

    playback_points = [
        n
        for n in sidecar.output.notifications_named("location.updated")
        if n["source"] == "playback"
    ]
    assert len(playback_points) >= 4
    states = [n["state"] for n in sidecar.output.notifications_named("playback.state")]
    assert states == ["playing", "paused", "playing", "idle"]

    assert await sidecar.result("location.clear") == {}
    assert sidecar.device.current is None
    assert await sidecar.result("device.disconnect") == {}
    assert sidecar.device.connected is None


async def test_playback_runs_to_the_end_and_parks(sidecar: Sidecar) -> None:
    await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
    await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": SPEED_KMH})
    await sidecar.result("playback.start")
    await settle()
    await sidecar.time.ticks(15)
    status = await sidecar.result("playback.status")
    assert status["state"] == "finished"
    assert status["progress"] == 1.0
    assert status["position"] == {"lat": 0.0, "lon": 0.01}
    states = [n["state"] for n in sidecar.output.notifications_named("playback.state")]
    assert states == ["playing", "finished"]


async def test_location_set_stops_playback(sidecar: Sidecar) -> None:
    await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
    await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": SPEED_KMH})
    await sidecar.result("playback.start")
    await sidecar.result("location.set", {"lat": 1, "lon": 1})
    assert (await sidecar.result("playback.status"))["state"] == "idle"
    assert sidecar.device.current is not None and sidecar.device.current.lat == 1.0


async def test_backend_failure_is_notified() -> None:
    sidecar = Sidecar(MockDevice(fail_set_after=2))
    try:
        await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
        await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": SPEED_KMH})
        await sidecar.result("playback.start")
        await settle()
        await sidecar.time.ticks(3)
        [error] = sidecar.output.notifications_named("playback.error")
        assert error["code"] == "DEVICE_DISCONNECTED"
        assert error["message"] and error["fix"]
        states = [n["state"] for n in sidecar.output.notifications_named("playback.state")]
        assert states == ["playing", "paused"]
    finally:
        await sidecar.close()


async def test_device_errors(sidecar: Sidecar) -> None:
    assert await sidecar.error("device.connect", {"id": "NOPE"}) == (-32000, "DEVICE_NOT_FOUND")
    assert await sidecar.error("location.set", {"lat": 1, "lon": 2}) == (-32000, "NOT_CONNECTED")
    assert await sidecar.error("playback.start") == (-32000, "NO_ROUTE_LOADED")
    await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
    await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": 5})
    assert await sidecar.error("playback.resume") == (-32000, "INVALID_STATE")


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("app.info", {"extra": 1}),
        ("device.connect", {}),
        ("device.connect", {"id": 5}),
        ("device.connect", {"id": ""}),
        ("location.set", {"lat": 1}),
        ("location.set", {"lat": "1", "lon": 2}),
        ("location.set", {"lat": True, "lon": 2}),
        ("location.set", {"lat": 91, "lon": 2}),
        ("location.set", {"lat": 1, "lon": 2, "alt": 3}),
        ("playback.load", {"points": ROUTE}),
        ("playback.load", {"points": "x", "speedKmh": 5}),
        ("playback.load", {"points": [[0, 0]], "speedKmh": 5}),
        ("playback.load", {"points": [[0, 0], [0, 0]], "speedKmh": 5}),
        ("playback.load", {"points": [[0, 0], [1]], "speedKmh": 5}),
        ("playback.load", {"points": [[0, 0], [1, "a"]], "speedKmh": 5}),
        ("playback.load", {"points": ROUTE, "speedKmh": 0}),
        ("playback.load", {"points": ROUTE, "speedKmh": 541}),
        ("playback.load", {"points": ROUTE, "speedKmh": 5, "loop": "yes"}),
        ("playback.load", {"points": ROUTE, "speedKmh": 5, "jitter": 1}),
        ("playback.setSpeed", {"speedKmh": -1}),
    ],
)
async def test_invalid_params(sidecar: Sidecar, method: str, params: dict[str, Any]) -> None:
    if method == "playback.setSpeed":
        await sidecar.result("playback.load", {"points": ROUTE, "speedKmh": 5})
    assert await sidecar.error(method, params) == (-32602, "INVALID_PARAMS")


async def test_load_with_loop_and_jitter(sidecar: Sidecar) -> None:
    result = await sidecar.result(
        "playback.load",
        {"points": [[0, 0], [0, 0], [0, 0.01]], "speedKmh": 5, "loop": True, "jitter": True},
    )
    assert result["points"] == 2  # the duplicate was dropped


async def test_points_are_capped() -> None:
    handlers = SidecarHandlers(MockDevice(), backend_name="mock", log_file=None)
    too_many = [[0.0, i * 1e-5] for i in range(MAX_ROUTE_POINTS + 1)]
    with pytest.raises(OpenLocateError) as info:
        await handlers.playback_load({"points": too_many, "speedKmh": 5})
    assert info.value.code is ErrorCode.INVALID_PARAMS
    assert "200000" in (info.value.detail or "")
