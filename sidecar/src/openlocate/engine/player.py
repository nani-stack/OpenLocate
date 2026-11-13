"""Route playback as a pure state machine. The caller pushes time in with advance()."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from openlocate.engine.geo import LatLon
from openlocate.engine.jitter import Jitter
from openlocate.engine.route import Route

MAX_SPEED_MPS = 150.0  # 540 km/h
SPEED_PRESETS_KMH: dict[str, float] = {"walk": 5.0, "bike": 16.0, "drive": 50.0}


def kmh_to_mps(kmh: float) -> float:
    return kmh / 3.6


def mps_to_kmh(mps: float) -> float:
    return mps * 3.6


class PlayerState(str, Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"


class PlayerStateError(Exception):
    """An action was requested that the current state does not allow."""


@dataclass(frozen=True)
class Fix:
    """One playback step. position has jitter applied; distance_m is the true distance."""

    position: LatLon
    distance_m: float
    speed_mps: float
    bearing_deg: float
    state: PlayerState
    progress: float
    lap: int


def _validate_speed(speed_mps: float) -> float:
    if not (math.isfinite(speed_mps) and 0.0 < speed_mps <= MAX_SPEED_MPS):
        raise ValueError(
            f"speed must be above 0 and at most {MAX_SPEED_MPS:g} m/s "
            f"({mps_to_kmh(MAX_SPEED_MPS):g} km/h), got {speed_mps} m/s"
        )
    return float(speed_mps)


class Player:
    """Moves along a route at a set speed. States: idle, playing, paused, finished."""

    def __init__(
        self,
        route: Route,
        speed_mps: float,
        *,
        loop: bool = False,
        jitter: Jitter | None = None,
    ) -> None:
        self._route = route
        self._speed_mps = _validate_speed(speed_mps)
        self._loop = loop
        self._jitter = jitter
        self._state = PlayerState.IDLE
        self._distance_m = 0.0
        self._lap = 0

    @property
    def route(self) -> Route:
        return self._route

    @property
    def state(self) -> PlayerState:
        return self._state

    @property
    def speed_mps(self) -> float:
        return self._speed_mps

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def distance_m(self) -> float:
        return self._distance_m

    @property
    def lap(self) -> int:
        return self._lap

    @property
    def progress(self) -> float:
        return self._distance_m / self._route.length_m

    def _require(self, action: str, *allowed: PlayerState) -> None:
        if self._state not in allowed:
            names = " or ".join(s.value for s in allowed)
            raise PlayerStateError(
                f"cannot {action} while {self._state.value} (only while {names})"
            )

    def start(self) -> None:
        """Start from the beginning. Allowed when idle or finished."""
        self._require("start", PlayerState.IDLE, PlayerState.FINISHED)
        self._distance_m = 0.0
        self._lap = 0
        self._state = PlayerState.PLAYING

    def pause(self) -> None:
        self._require("pause", PlayerState.PLAYING)
        self._state = PlayerState.PAUSED

    def resume(self) -> None:
        self._require("resume", PlayerState.PAUSED)
        self._state = PlayerState.PLAYING

    def stop(self) -> None:
        """Return to idle at the start of the route."""
        self._require("stop", PlayerState.PLAYING, PlayerState.PAUSED, PlayerState.FINISHED)
        self._state = PlayerState.IDLE
        self._distance_m = 0.0
        self._lap = 0

    def set_speed(self, speed_mps: float) -> None:
        """Takes effect from the next advance(); distance already covered is kept."""
        self._speed_mps = _validate_speed(speed_mps)

    def advance(self, dt_seconds: float) -> Fix:
        """Move forward by dt_seconds of travel (only while playing) and report the position."""
        if not (math.isfinite(dt_seconds) and dt_seconds >= 0.0):
            raise ValueError(f"dt_seconds must be finite and >= 0, got {dt_seconds}")

        speed_used = 0.0
        if self._state is PlayerState.PLAYING:
            factor = self._jitter.speed_factor() if self._jitter and dt_seconds > 0 else 1.0
            speed_used = self._speed_mps * factor
            self._move(speed_used * dt_seconds)
        return self._fix(speed_used)

    def _move(self, step_m: float) -> None:
        target = self._distance_m + step_m
        if not math.isfinite(target):
            raise ValueError("time step is too large")
        length = self._route.length_m
        if target < length:
            self._distance_m = target
        elif not self._loop:
            self._distance_m = length
            self._state = PlayerState.FINISHED
        else:
            # divmod handles a step longer than several laps without recursion or loops.
            laps, remainder = divmod(target, length)
            self._distance_m = remainder
            self._lap += int(laps)

    def _fix(self, speed_used: float) -> Fix:
        if self._state is PlayerState.FINISHED:
            # Parked: exactly the destination, no jitter.
            position = self._route.points[-1]
            progress = 1.0
        else:
            position = self._route.point_at(self._distance_m)
            if self._jitter is not None and self._state is not PlayerState.IDLE:
                position = self._jitter.offset(position)
            progress = self.progress
        return Fix(
            position=position,
            distance_m=self._distance_m,
            speed_mps=speed_used,
            bearing_deg=self._route.bearing_at(self._distance_m),
            state=self._state,
            progress=progress,
            lap=self._lap,
        )
