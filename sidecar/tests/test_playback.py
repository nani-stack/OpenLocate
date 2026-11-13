from __future__ import annotations

import pytest

from conftest import FakeTime, settle
from openlocate.device.mock import MOCK_DEVICE_ID, MockDevice
from openlocate.engine.geo import LatLon, haversine_m
from openlocate.engine.player import Fix, PlayerState
from openlocate.engine.route import Route
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.playback import MAX_TICK_ELAPSED_S, PlaybackRunner

START = LatLon(0.0, 0.0)
END = LatLon(0.0, 0.01)  # about 1112 m
SPEED = 100.0  # m/s, so one tick is 100 m


class Harness:
    def __init__(self, device: MockDevice) -> None:
        self.device = device
        self.time = FakeTime()
        self.fixes: list[Fix] = []
        self.errors: list[OpenLocateError] = []
        self.runner = PlaybackRunner(
            device,
            clock=self.time.clock,
            sleep=self.time.sleep,
            on_fix=self.fixes.append,
            on_error=self.errors.append,
        )

    @property
    def sent(self) -> list[LatLon | None]:
        return [point for _, point in self.device.history]


async def make(device: MockDevice | None = None, *, loop: bool = False) -> Harness:
    device = device or MockDevice()
    await device.connect(MOCK_DEVICE_ID)
    harness = Harness(device)
    await harness.runner.load(Route([START, END]), SPEED, loop=loop)
    return harness


async def test_positions_arrive_in_order_and_finish_exactly() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    assert h.sent == [START]  # the start point is sent straight away

    await h.time.ticks(20)
    longitudes = [p.lon for p in h.sent if p is not None]
    assert longitudes == sorted(longitudes)
    assert h.sent[-1] == END  # exactly the destination
    assert h.sent.count(END) == 1  # sent once, then ticking stops
    assert h.runner.state is PlayerState.FINISHED
    assert not h.runner.is_ticking
    assert h.time.sleepers == 0
    assert h.device.current == END  # not cleared
    assert [f.position for f in h.fixes] == h.sent
    assert h.runner.status()["progress"] == 1.0


async def test_each_tick_moves_speed_times_elapsed() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    await h.time.ticks(3)
    assert h.runner.status()["distance_m"] == pytest.approx(300.0)
    await h.time.advance(2.5)  # a late tick: elapsed time is measured, not assumed
    assert h.runner.status()["distance_m"] == pytest.approx(550.0)


async def test_pause_and_resume() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    await h.time.ticks(3)
    await h.runner.pause()
    sent_before = len(h.sent)
    await h.time.ticks(10)
    status = h.runner.status()
    assert status["state"] == "paused"
    assert status["distance_m"] == pytest.approx(300.0)
    assert len(h.sent) > sent_before  # a paused phone keeps receiving its position

    h.time.now += 30.0  # time passes while paused; it must not count as travel
    await h.runner.resume()
    await h.time.ticks(1)
    assert h.runner.status()["distance_m"] == pytest.approx(400.0)


async def test_elapsed_time_per_tick_is_capped() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    await h.time.advance(60.0)  # a laptop waking from sleep
    assert h.runner.status()["distance_m"] == pytest.approx(SPEED * MAX_TICK_ELAPSED_S)


async def test_backend_failure_pauses_and_reports() -> None:
    h = await make(MockDevice(fail_set_after=3))
    await h.runner.start()
    await settle()
    await h.time.ticks(5)
    assert h.runner.state is PlayerState.PAUSED
    assert not h.runner.is_ticking  # no spinning
    assert h.time.sleepers == 0
    assert [e.code for e in h.errors] == [ErrorCode.DEVICE_DISCONNECTED]
    assert h.runner.last_error is h.errors[0]
    distance = h.runner.status()["distance_m"]

    await h.device.connect(MOCK_DEVICE_ID)
    h.device._fail_set_after = None  # the phone is back
    await h.runner.resume()
    await settle()
    assert h.runner.is_ticking
    assert h.runner.last_error is None
    await h.time.ticks(1)
    assert h.runner.status()["distance_m"] == pytest.approx(distance + SPEED)


async def test_untranslated_backend_exception_becomes_internal() -> None:
    h = await make()
    await h.runner.start()
    await settle()

    async def broken(point: LatLon) -> None:
        raise KeyError("library detail")

    h.device.set_location = broken  # type: ignore[method-assign]
    await h.time.ticks(1)
    assert [e.code for e in h.errors] == [ErrorCode.INTERNAL]
    assert h.runner.state is PlayerState.PAUSED


async def test_start_reports_a_failing_first_send_directly() -> None:
    h = await make(MockDevice(fail_set_after=0))
    with pytest.raises(OpenLocateError) as info:
        await h.runner.start()
    assert info.value.code is ErrorCode.DEVICE_DISCONNECTED
    assert h.runner.state is PlayerState.IDLE
    assert not h.runner.is_ticking
    assert h.errors == []  # reported to the caller, not through on_error


async def test_resume_after_an_error_fails_while_the_phone_is_still_gone() -> None:
    h = await make(MockDevice(fail_set_after=1))
    await h.runner.start()
    await settle()
    await h.time.ticks(1)
    assert h.runner.state is PlayerState.PAUSED
    with pytest.raises(OpenLocateError) as info:
        await h.runner.resume()
    assert info.value.code is ErrorCode.NOT_CONNECTED
    assert h.runner.state is PlayerState.PAUSED
    assert not h.runner.is_ticking


async def test_stop_cancels_and_keeps_the_location() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    await h.time.ticks(2)
    last = h.device.current
    await h.runner.stop()
    assert not h.runner.is_ticking
    assert h.runner.state is PlayerState.IDLE
    assert h.device.current == last
    await h.time.ticks(3)
    assert h.device.current == last


async def test_set_speed_mid_route() -> None:
    h = await make()
    await h.runner.start()
    await settle()
    await h.time.ticks(2)
    await h.runner.set_speed(50.0)
    await h.time.ticks(2)
    assert h.runner.status()["distance_m"] == pytest.approx(300.0)
    with pytest.raises(OpenLocateError) as info:
        await h.runner.set_speed(0.0)
    assert info.value.code is ErrorCode.INVALID_PARAMS


async def test_loop_keeps_going_and_counts_laps() -> None:
    h = await make(loop=True)
    await h.runner.start()
    await settle()
    await h.time.ticks(12)  # 1200 m on a ~1112 m route
    status = h.runner.status()
    assert status["lap"] == 1
    assert status["state"] == "playing"
    assert status["distance_m"] == pytest.approx(1200.0 - haversine_m(START, END))


async def test_errors_for_wrong_order_of_calls() -> None:
    device = MockDevice()
    runner = PlaybackRunner(device)
    for call in (runner.start, runner.pause, runner.resume):
        with pytest.raises(OpenLocateError) as info:
            await call()
        assert info.value.code is ErrorCode.NO_ROUTE_LOADED

    await runner.load(Route([START, END]), SPEED)
    with pytest.raises(OpenLocateError) as info:
        await runner.start()
    assert info.value.code is ErrorCode.NOT_CONNECTED
    with pytest.raises(OpenLocateError) as info:
        await runner.pause()
    assert info.value.code is ErrorCode.INVALID_STATE
    await runner.stop()  # stopping when idle is harmless


async def test_load_rejects_invalid_speed() -> None:
    runner = PlaybackRunner(MockDevice())
    with pytest.raises(OpenLocateError) as info:
        await runner.load(Route([START, END]), 1_000.0)
    assert info.value.code is ErrorCode.INVALID_PARAMS


def test_status_without_a_route() -> None:
    status = PlaybackRunner(MockDevice()).status()
    assert status["state"] == "idle"
    assert status["position"] is None
