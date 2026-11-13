import math

import pytest

from openlocate.engine.geo import (
    LatLon,
    destination,
    haversine_m,
    initial_bearing_deg,
    interpolate,
)

LONDON = LatLon(51.5074, -0.1278)
PARIS = LatLon(48.8566, 2.3522)


def test_london_to_paris_distance() -> None:
    expected = 343_500.0  # published great-circle distance, about 343.5 km
    assert haversine_m(LONDON, PARIS) == pytest.approx(expected, rel=0.005)


def test_distance_is_zero_for_the_same_point_and_symmetric() -> None:
    assert haversine_m(LONDON, LONDON) == 0.0
    assert haversine_m(LONDON, PARIS) == pytest.approx(haversine_m(PARIS, LONDON))


def test_quarter_meridian() -> None:
    quarter = haversine_m(LatLon(0, 0), LatLon(90, 0))
    assert quarter == pytest.approx(math.pi / 2 * 6_371_008.8)


@pytest.mark.parametrize(
    ("target", "bearing"),
    [
        (LatLon(1, 0), 0.0),
        (LatLon(0, 1), 90.0),
        (LatLon(-1, 0), 180.0),
        (LatLon(0, -1), 270.0),
    ],
)
def test_cardinal_bearings(target: LatLon, bearing: float) -> None:
    assert initial_bearing_deg(LatLon(0, 0), target) == pytest.approx(bearing)


def test_london_to_paris_bearing() -> None:
    assert initial_bearing_deg(LONDON, PARIS) == pytest.approx(148.1, abs=0.5)


def test_bearing_is_in_range() -> None:
    value = initial_bearing_deg(LatLon(0, 0), LatLon(-1e-12, -1))
    assert 0.0 <= value < 360.0


@pytest.mark.parametrize("bearing", [0.0, 45.0, 133.7, 270.0, 359.0])
def test_destination_round_trip(bearing: float) -> None:
    end = destination(LONDON, bearing, 12_345.0)
    assert haversine_m(LONDON, end) == pytest.approx(12_345.0, rel=1e-9)
    difference = (initial_bearing_deg(LONDON, end) - bearing + 180.0) % 360.0 - 180.0
    assert abs(difference) < 1e-6


def test_destination_wraps_across_the_antimeridian() -> None:
    end = destination(LatLon(0, 179.9), 90.0, 50_000.0)
    assert -180.0 <= end.lon < -179.0


def test_interpolate_endpoints_and_clamping() -> None:
    assert interpolate(LONDON, PARIS, 0.0) == LONDON
    assert interpolate(LONDON, PARIS, 1.0) == PARIS
    assert interpolate(LONDON, PARIS, -3.0) == LONDON
    assert interpolate(LONDON, PARIS, 7.0) == PARIS


def test_interpolate_midpoint_is_halfway() -> None:
    mid = interpolate(LONDON, PARIS, 0.5)
    total = haversine_m(LONDON, PARIS)
    assert haversine_m(LONDON, mid) == pytest.approx(total / 2, rel=1e-9)
    assert haversine_m(mid, PARIS) == pytest.approx(total / 2, rel=1e-9)


def test_interpolate_across_the_antimeridian_takes_the_short_way() -> None:
    a, b = LatLon(10, 179.0), LatLon(10, -179.0)
    mid = interpolate(a, b, 0.5)
    assert abs(abs(mid.lon) - 180.0) < 1e-6
    assert mid.lat == pytest.approx(10.0, abs=0.01)
    quarter = interpolate(a, b, 0.25)
    assert quarter.lon == pytest.approx(179.5, abs=1e-3)
    assert haversine_m(a, quarter) == pytest.approx(haversine_m(a, b) / 4, rel=1e-9)


def test_interpolate_rejects_antipodal_points() -> None:
    with pytest.raises(ValueError, match="antipodal"):
        interpolate(LatLon(0, 0), LatLon(0, 180), 0.5)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (91.0, 0.0),
        (-90.5, 0.0),
        (0.0, 180.1),
        (0.0, -181.0),
        (math.nan, 0.0),
        (0.0, math.inf),
    ],
)
def test_latlon_rejects_out_of_range_or_non_finite(lat: float, lon: float) -> None:
    with pytest.raises(ValueError):
        LatLon(lat, lon)


def test_latlon_rejects_non_numbers() -> None:
    with pytest.raises(ValueError):
        LatLon("1", 2)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LatLon(True, 2)


def test_latlon_accepts_the_edges_and_stores_floats() -> None:
    point = LatLon(90, -180)
    assert point.lat == 90.0 and isinstance(point.lat, float)
