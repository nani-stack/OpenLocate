import pytest

from openlocate.engine.geo import LatLon, haversine_m
from openlocate.engine.route import Route

A = LatLon(0.0, 0.0)
B = LatLon(0.0, 0.01)
C = LatLon(0.01, 0.01)


def test_length_is_the_sum_of_segments() -> None:
    route = Route([A, B, C])
    assert route.length_m == pytest.approx(haversine_m(A, B) + haversine_m(B, C))
    assert route.cumulative_m[0] == 0.0
    assert route.cumulative_m[-1] == route.length_m


def test_point_at_start_middle_end_and_beyond() -> None:
    route = Route([A, B, C])
    assert route.point_at(0.0) == A
    assert route.point_at(-5.0) == A
    assert route.point_at(route.length_m) == C
    assert route.point_at(route.length_m + 1_000.0) == C
    first_leg = haversine_m(A, B)
    assert haversine_m(route.point_at(first_leg), B) < 1e-6
    middle_of_first = route.point_at(first_leg / 2)
    assert haversine_m(A, middle_of_first) == pytest.approx(first_leg / 2, rel=1e-9)
    into_second = route.point_at(first_leg + 100.0)
    assert haversine_m(B, into_second) == pytest.approx(100.0, rel=1e-6)


def test_bearing_at_follows_the_segments() -> None:
    route = Route([A, B, C])
    assert route.bearing_at(10.0) == pytest.approx(90.0, abs=0.01)
    assert route.bearing_at(route.length_m - 10.0) == pytest.approx(0.0, abs=0.01)
    assert route.bearing_at(route.length_m + 50.0) == pytest.approx(0.0, abs=0.01)


def test_consecutive_duplicates_are_dropped() -> None:
    route = Route([A, A, B, B, B, C])
    assert route.points == (A, B, C)
    # A repeat that is not consecutive is a real part of the route.
    assert Route([A, B, A]).points == (A, B, A)


@pytest.mark.parametrize("points", [[], [A], [A, A], [B, B, B]])
def test_too_few_distinct_points(points: list[LatLon]) -> None:
    with pytest.raises(ValueError, match="at least 2"):
        Route(points)


def test_non_finite_distance_is_rejected() -> None:
    with pytest.raises(ValueError):
        Route([A, B]).point_at(float("nan"))


def test_antipodal_segment_is_rejected() -> None:
    with pytest.raises(ValueError, match="opposite sides"):
        Route([LatLon(0, 0), LatLon(0, 180)])
