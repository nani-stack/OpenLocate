import math

import pytest

from openlocate.engine.geo import LatLon, haversine_m
from openlocate.engine.jitter import Jitter, JitterConfig
from openlocate.engine.player import (
    MAX_SPEED_MPS,
    SPEED_PRESETS_KMH,
    Player,
    PlayerState,
    PlayerStateError,
    kmh_to_mps,
)
from openlocate.engine.route import Route

START = LatLon(0.0, 0.0)
END = LatLon(0.0, 0.01)  # about 1112 m east


@pytest.fixture
def route() -> Route:
    return Route([START, END])


def playing(route: Route, speed: float = 10.0, **kwargs: object) -> Player:
    player = Player(route, speed, **kwargs)  # type: ignore[arg-type]
    player.start()
    return player


def test_starts_idle_at_the_start(route: Route) -> None:
    player = Player(route, 10.0)
    fix = player.advance(5.0)
    assert fix.state is PlayerState.IDLE
    assert fix.distance_m == 0.0
    assert fix.position == START
    assert fix.lap == 0


def test_constant_speed_covers_speed_times_time(route: Route) -> None:
    player = playing(route, 10.0)
    for _ in range(30):
        fix = player.advance(1.0)
    assert fix.distance_m == pytest.approx(300.0)
    assert fix.speed_mps == 10.0
    assert haversine_m(START, fix.position) == pytest.approx(300.0, rel=1e-6)
    assert fix.progress == pytest.approx(300.0 / route.length_m)
    assert fix.bearing_deg == pytest.approx(90.0, abs=0.01)


def test_pause_holds_distance_and_resume_continues(route: Route) -> None:
    player = playing(route, 10.0)
    player.advance(10.0)
    player.pause()
    fix = player.advance(100.0)
    assert fix.state is PlayerState.PAUSED
    assert fix.distance_m == pytest.approx(100.0)
    assert fix.speed_mps == 0.0
    player.resume()
    assert player.advance(5.0).distance_m == pytest.approx(150.0)


def test_paused_position_wanders_a_little_with_jitter(route: Route) -> None:
    jitter = Jitter(JitterConfig(speed_fraction=0.0, position_m=1.0), seed=7)
    player = playing(route, 10.0, jitter=jitter)
    player.advance(10.0)
    player.pause()
    true_point = route.point_at(100.0)
    offsets = [haversine_m(true_point, player.advance(1.0).position) for _ in range(50)]
    assert max(offsets) <= 2.0 + 1e-6
    assert max(offsets) > 0.0


def test_speed_change_mid_route_keeps_distance(route: Route) -> None:
    player = playing(route, 10.0)
    player.advance(10.0)  # 100 m
    player.set_speed(20.0)
    assert player.distance_m == pytest.approx(100.0)
    fix = player.advance(10.0)  # +200 m
    assert fix.distance_m == pytest.approx(300.0)
    assert fix.speed_mps == 20.0


def test_finish_parks_on_the_exact_last_point() -> None:
    jitter = Jitter(JitterConfig(position_m=5.0), seed=9)
    route = Route([START, END])
    player = playing(route, 100.0, jitter=jitter)
    fix = player.advance(1_000.0)
    assert fix.state is PlayerState.FINISHED
    assert fix.position == END
    assert fix.distance_m == route.length_m
    assert fix.progress == 1.0
    again = player.advance(10.0)
    assert again.state is PlayerState.FINISHED
    assert again.position == END


def test_loop_wraps_and_counts_laps(route: Route) -> None:
    length = route.length_m
    player = playing(route, 10.0, loop=True)
    fix = player.advance((length + 50.0) / 10.0)
    assert fix.state is PlayerState.PLAYING
    assert fix.lap == 1
    assert fix.distance_m == pytest.approx(50.0, abs=1e-6)


def test_loop_with_a_step_longer_than_several_laps(route: Route) -> None:
    length = route.length_m
    player = playing(route, 100.0, loop=True)
    fix = player.advance((3.5 * length) / 100.0)
    assert fix.lap == 3
    assert fix.distance_m == pytest.approx(length / 2, rel=1e-9)


def test_huge_step_in_loop_mode_does_not_recurse(route: Route) -> None:
    player = playing(route, MAX_SPEED_MPS, loop=True)
    fix = player.advance(1e9)
    expected_laps = math.floor(MAX_SPEED_MPS * 1e9 / route.length_m)
    assert abs(fix.lap - expected_laps) <= 1  # float rounding at the lap boundary
    assert 0.0 <= fix.distance_m < route.length_m


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_invalid_transitions_from_idle(route: Route, action: str) -> None:
    player = Player(route, 10.0)
    with pytest.raises(PlayerStateError, match="idle"):
        getattr(player, action)()


def test_invalid_transitions_while_playing(route: Route) -> None:
    player = playing(route)
    with pytest.raises(PlayerStateError):
        player.start()
    with pytest.raises(PlayerStateError):
        player.resume()


def test_start_again_after_finishing_and_stop_resets(route: Route) -> None:
    player = playing(route, 100.0)
    player.advance(100.0)
    assert player.state is PlayerState.FINISHED
    player.start()
    assert player.distance_m == 0.0
    player.advance(1.0)
    player.stop()
    assert player.state is PlayerState.IDLE
    assert player.distance_m == 0.0


@pytest.mark.parametrize("speed", [0.0, -1.0, MAX_SPEED_MPS + 0.01, math.nan, math.inf])
def test_invalid_speeds_raise(route: Route, speed: float) -> None:
    with pytest.raises(ValueError):
        Player(route, speed)
    player = Player(route, 10.0)
    with pytest.raises(ValueError):
        player.set_speed(speed)


@pytest.mark.parametrize("dt", [-0.1, math.nan, math.inf])
def test_invalid_dt_raises(route: Route, dt: float) -> None:
    with pytest.raises(ValueError):
        playing(route).advance(dt)


def test_speed_presets_and_conversion() -> None:
    assert SPEED_PRESETS_KMH == {"walk": 5.0, "bike": 16.0, "drive": 50.0}
    assert kmh_to_mps(36.0) == pytest.approx(10.0)
    assert kmh_to_mps(540.0) == pytest.approx(MAX_SPEED_MPS)
