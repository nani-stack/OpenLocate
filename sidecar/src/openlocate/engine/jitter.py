"""Seeded noise that makes simulated movement look less robotic."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from openlocate.engine.geo import LatLon, destination

# How much of the previous speed drift is kept each step. Closer to 1 means slower drift.
_SPEED_SMOOTHING = 0.9


@dataclass(frozen=True)
class JitterConfig:
    """speed_fraction: maximum relative speed change (0.05 = +/-5 %).
    position_m: typical position noise; a single offset never exceeds 2 * position_m.
    """

    speed_fraction: float = 0.05
    position_m: float = 1.5
    enabled: bool = True

    def __post_init__(self) -> None:
        if not (math.isfinite(self.speed_fraction) and 0.0 <= self.speed_fraction < 1.0):
            raise ValueError(f"speed_fraction must be in [0, 1), got {self.speed_fraction}")
        if not (math.isfinite(self.position_m) and self.position_m >= 0.0):
            raise ValueError(f"position_m must be >= 0, got {self.position_m}")


class Jitter:
    """Speed and position noise from its own random generator, so a seed reproduces it."""

    def __init__(self, config: JitterConfig, seed: int | None = None) -> None:
        self._config = config
        self._rng = random.Random(seed)
        self._drift = 0.0  # always within [-1, 1]

    @property
    def config(self) -> JitterConfig:
        return self._config

    def speed_factor(self) -> float:
        """A multiplier around 1.0 that drifts smoothly, within 1 +/- speed_fraction."""
        if not self._config.enabled:
            return 1.0
        # Low-pass filter: a convex mix of values in [-1, 1] stays in [-1, 1].
        sample = self._rng.uniform(-1.0, 1.0)
        self._drift = _SPEED_SMOOTHING * self._drift + (1.0 - _SPEED_SMOOTHING) * sample
        return 1.0 + self._config.speed_fraction * self._drift

    def offset(self, point: LatLon) -> LatLon:
        """The point moved in a random direction by at most 2 * position_m metres."""
        if not self._config.enabled or self._config.position_m == 0.0:
            return point
        bearing = self._rng.uniform(0.0, 360.0)
        # Triangular with its mode at 0: small offsets are common, the cap is never exceeded.
        distance = self._rng.triangular(0.0, 2.0 * self._config.position_m, 0.0)
        return destination(point, bearing, distance)
