"""A route: a polyline of positions with cumulative distances along it."""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

from openlocate.engine.geo import (
    EARTH_RADIUS_M,
    LatLon,
    haversine_m,
    initial_bearing_deg,
    interpolate,
)

# Segments this close to half the earth's circumference have no well-defined great circle.
_MAX_SEGMENT_M = math.pi * EARTH_RADIUS_M - 1_000.0


class Route:
    """An immutable polyline. Consecutive duplicate points are dropped."""

    def __init__(self, points: Sequence[LatLon]) -> None:
        if len(points) < 2:
            raise ValueError(f"a route needs at least 2 points, got {len(points)}")

        kept: list[LatLon] = [points[0]]
        cumulative: list[float] = [0.0]
        for point in points[1:]:
            step = haversine_m(kept[-1], point)
            if step == 0.0:
                continue
            if step > _MAX_SEGMENT_M:
                raise ValueError("two consecutive route points are on opposite sides of the earth")
            kept.append(point)
            cumulative.append(cumulative[-1] + step)

        if len(kept) < 2:
            raise ValueError("a route needs at least 2 distinct points")
        self._points: tuple[LatLon, ...] = tuple(kept)
        self._cumulative: tuple[float, ...] = tuple(cumulative)

    @property
    def points(self) -> tuple[LatLon, ...]:
        return self._points

    @property
    def cumulative_m(self) -> tuple[float, ...]:
        """Distance from the start to each point, in metres."""
        return self._cumulative

    @property
    def length_m(self) -> float:
        return self._cumulative[-1]

    def _segment_index(self, distance_m: float) -> int:
        """Index i of the segment points[i] -> points[i + 1] that contains distance_m."""
        index = bisect.bisect_right(self._cumulative, distance_m) - 1
        return max(0, min(index, len(self._points) - 2))

    def point_at(self, distance_m: float) -> LatLon:
        """The position distance_m along the route, clamped to the start and the end."""
        if not math.isfinite(distance_m):
            raise ValueError(f"distance_m must be finite, got {distance_m}")
        if distance_m <= 0.0:
            return self._points[0]
        if distance_m >= self.length_m:
            return self._points[-1]
        i = self._segment_index(distance_m)
        segment_m = self._cumulative[i + 1] - self._cumulative[i]
        fraction = (distance_m - self._cumulative[i]) / segment_m
        return interpolate(self._points[i], self._points[i + 1], fraction)

    def bearing_at(self, distance_m: float) -> float:
        """Direction of travel (degrees, 0 to 360) on the segment containing distance_m."""
        if not math.isfinite(distance_m):
            raise ValueError(f"distance_m must be finite, got {distance_m}")
        i = self._segment_index(distance_m)
        return initial_bearing_deg(self._points[i], self._points[i + 1])
