"""Spherical-earth geometry: distances, bearings, destination points and interpolation."""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_008.8

# Below this angular distance two points are treated as the same place (about 6 micrometres).
_SAME_POINT_RAD = 1e-12
# Within this angle of 180 degrees the great circle between two points is not unique.
_ANTIPODAL_RAD = 1e-9


def _require_finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    return float(value)


@dataclass(frozen=True)
class LatLon:
    """A position in degrees. Latitude in [-90, 90], longitude in [-180, 180]."""

    lat: float
    lon: float

    def __post_init__(self) -> None:
        lat = _require_finite_number("lat", self.lat)
        lon = _require_finite_number("lon", self.lon)
        if not -90.0 <= lat <= 90.0:
            raise ValueError(f"lat must be between -90 and 90, got {lat}")
        if not -180.0 <= lon <= 180.0:
            raise ValueError(f"lon must be between -180 and 180, got {lon}")
        # Store plain floats even if ints were passed.
        object.__setattr__(self, "lat", lat)
        object.__setattr__(self, "lon", lon)


def normalize_lon(lon_deg: float) -> float:
    """Wrap a longitude into [-180, 180)."""
    return (lon_deg + 180.0) % 360.0 - 180.0


def _from_radians(lat_rad: float, lon_rad: float) -> LatLon:
    lat = max(-90.0, min(90.0, math.degrees(lat_rad)))
    return LatLon(lat, normalize_lon(math.degrees(lon_rad)))


def _angular_distance_rad(a: LatLon, b: LatLon) -> float:
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_phi = phi2 - phi1
    d_lambda = math.radians(b.lon - a.lon)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2.0 * math.asin(min(1.0, math.sqrt(h)))


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance in metres."""
    return EARTH_RADIUS_M * _angular_distance_rad(a, b)


def initial_bearing_deg(a: LatLon, b: LatLon) -> float:
    """Bearing from a towards b at the start of the great circle, in [0, 360)."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_lambda = math.radians(b.lon - a.lon)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    bearing = math.degrees(math.atan2(y, x)) % 360.0
    return 0.0 if bearing >= 360.0 else bearing


def destination(origin: LatLon, bearing_deg: float, distance_m: float) -> LatLon:
    """The point reached by travelling distance_m along a great circle from origin."""
    bearing_deg = _require_finite_number("bearing_deg", bearing_deg)
    distance_m = _require_finite_number("distance_m", distance_m)
    delta = distance_m / EARTH_RADIUS_M
    theta = math.radians(bearing_deg)
    phi1, lambda1 = math.radians(origin.lat), math.radians(origin.lon)

    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    phi2 = math.asin(max(-1.0, min(1.0, sin_phi2)))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return _from_radians(phi2, lambda2)


def interpolate(a: LatLon, b: LatLon, fraction: float) -> LatLon:
    """The point at `fraction` of the way from a to b along the great circle.

    Works across the antimeridian. `fraction` is clamped to [0, 1]. Raises ValueError for
    (nearly) antipodal points, where the great circle is not unique.
    """
    fraction = _require_finite_number("fraction", fraction)
    fraction = max(0.0, min(1.0, fraction))
    if fraction == 0.0:
        return a
    if fraction == 1.0:
        return b

    delta = _angular_distance_rad(a, b)
    if delta < _SAME_POINT_RAD:
        return a
    if math.pi - delta < _ANTIPODAL_RAD:
        raise ValueError("cannot interpolate between antipodal points")

    # Spherical linear interpolation of the two unit vectors.
    sin_delta = math.sin(delta)
    weight_a = math.sin((1.0 - fraction) * delta) / sin_delta
    weight_b = math.sin(fraction * delta) / sin_delta
    phi1, lambda1 = math.radians(a.lat), math.radians(a.lon)
    phi2, lambda2 = math.radians(b.lat), math.radians(b.lon)
    x = weight_a * math.cos(phi1) * math.cos(lambda1) + weight_b * math.cos(phi2) * math.cos(
        lambda2
    )
    y = weight_a * math.cos(phi1) * math.sin(lambda1) + weight_b * math.cos(phi2) * math.sin(
        lambda2
    )
    z = weight_a * math.sin(phi1) + weight_b * math.sin(phi2)
    return _from_radians(math.atan2(z, math.hypot(x, y)), math.atan2(y, x))
