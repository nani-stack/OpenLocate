"""Road routing: turning a few waypoints into a path that follows real roads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from openlocate.engine.geo import LatLon

MAX_WAYPOINTS = 25


class Profile(str, Enum):
    """How the trip is made. Decides which roads and paths may be used."""

    WALK = "walk"
    BIKE = "bike"
    DRIVE = "drive"


@dataclass(frozen=True)
class RoadRoute:
    """A routed path. duration_s is the router's own estimate for this profile."""

    points: tuple[LatLon, ...]
    distance_m: float
    duration_s: float

    @property
    def average_speed_mps(self) -> float:
        return self.distance_m / self.duration_s


class Router(Protocol):
    async def route(self, waypoints: list[LatLon], profile: Profile) -> RoadRoute:
        """Route through the waypoints in order. Raises OpenLocateError on failure."""
        ...
