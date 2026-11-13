"""PlaybackRunner: drives a Player with a real (or injected) clock and feeds the device."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import TypedDict

from openlocate.device.base import DeviceBackend
from openlocate.engine.geo import LatLon
from openlocate.engine.jitter import Jitter
from openlocate.engine.player import Fix, Player, PlayerState, PlayerStateError
from openlocate.engine.route import Route
from openlocate.errors import ErrorCode, OpenLocateError

log = logging.getLogger(__name__)

# A laptop waking from sleep must not teleport the phone far along the route.
MAX_TICK_ELAPSED_S = 5.0


class PlaybackStatus(TypedDict):
    state: str
    distance_m: float
    length_m: float
    progress: float
    speed_mps: float
    lap: int
    position: LatLon | None


class PlaybackRunner:
    """Owns the ticking loop. Every public method raises only OpenLocateError.

    While playing or paused, one background task ticks every `tick_seconds`, advances the
    player by the measured elapsed time and sends the position to the backend. Paused ticks
    keep sending the (slightly jittered) current point. When the route finishes, the exact
    final point is sent once and ticking stops; the location is never cleared here.
    """

    def __init__(
        self,
        backend: DeviceBackend,
        *,
        tick_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_fix: Callable[[Fix], None] | None = None,
        on_error: Callable[[OpenLocateError], None] | None = None,
    ) -> None:
        if not (math.isfinite(tick_seconds) and tick_seconds > 0):
            raise ValueError(f"tick_seconds must be > 0, got {tick_seconds}")
        self._backend = backend
        self._tick_seconds = tick_seconds
        self._clock = clock
        self._sleep = sleep
        self._on_fix = on_fix
        self._on_error = on_error
        self._player: Player | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_tick = 0.0
        self._last_fix: Fix | None = None
        self.last_error: OpenLocateError | None = None

    @property
    def state(self) -> PlayerState:
        return self._player.state if self._player else PlayerState.IDLE

    @property
    def is_ticking(self) -> bool:
        return self._task is not None and not self._task.done()

    async def load(
        self,
        route: Route,
        speed_mps: float,
        loop: bool = False,
        jitter: Jitter | None = None,
    ) -> None:
        """Replace the current route. Stops any playback first."""
        await self.stop()
        try:
            player = Player(route, speed_mps, loop=loop, jitter=jitter)
        except ValueError as err:
            raise OpenLocateError(ErrorCode.INVALID_PARAMS, str(err)) from err
        self._player = player
        self._last_fix = None
        self.last_error = None

    async def start(self) -> None:
        player = self._require_player()
        if self._backend.connected is None:
            raise OpenLocateError(ErrorCode.NOT_CONNECTED)
        _apply(player.start)
        try:
            await self._send_current_point(player)
        except OpenLocateError:
            player.stop()
            raise
        self.last_error = None
        await self._launch(player)

    async def pause(self) -> None:
        _apply(self._require_player().pause)

    async def resume(self) -> None:
        player = self._require_player()
        _apply(player.resume)
        if self.is_ticking:
            # Do not count the paused time as travel time.
            self._last_tick = self._clock()
            return
        # The loop stopped after a backend error: check the device answers, then tick again.
        try:
            await self._send_current_point(player)
        except OpenLocateError:
            player.pause()
            raise
        self.last_error = None
        await self._launch(player)

    async def stop(self) -> None:
        """Cancel ticking and return to idle. Does not clear the location."""
        await self._cancel_task()
        if self._player is not None and self._player.state is not PlayerState.IDLE:
            self._player.stop()

    async def set_speed(self, speed_mps: float) -> None:
        player = self._require_player()
        try:
            player.set_speed(speed_mps)
        except ValueError as err:
            raise OpenLocateError(ErrorCode.INVALID_PARAMS, str(err)) from err

    def status(self) -> PlaybackStatus:
        player = self._player
        position = self._last_fix.position if self._last_fix else None
        if player is None:
            return PlaybackStatus(
                state=PlayerState.IDLE.value,
                distance_m=0.0,
                length_m=0.0,
                progress=0.0,
                speed_mps=0.0,
                lap=0,
                position=position,
            )
        finished = player.state is PlayerState.FINISHED
        return PlaybackStatus(
            state=player.state.value,
            distance_m=player.distance_m,
            length_m=player.route.length_m,
            progress=1.0 if finished else player.progress,
            speed_mps=player.speed_mps,
            lap=player.lap,
            position=position,
        )

    def _require_player(self) -> Player:
        if self._player is None:
            raise OpenLocateError(ErrorCode.NO_ROUTE_LOADED)
        return self._player

    async def _send_current_point(self, player: Player) -> None:
        """Send the player's current position now, so callers see the result immediately.

        Raises the backend's OpenLocateError instead of reporting it through on_error.
        """
        fix = player.advance(0.0)
        try:
            await self._backend.set_location(fix.position)
        except OpenLocateError:
            raise
        except Exception as exc:
            log.exception("backend raised an untranslated exception")
            raise OpenLocateError(ErrorCode.INTERNAL, type(exc).__name__) from exc
        self._accept(fix)

    async def _launch(self, player: Player) -> None:
        await self._cancel_task()
        self._last_tick = self._clock()
        self._task = asyncio.create_task(self._run(player), name="openlocate-playback")

    async def _cancel_task(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run(self, player: Player) -> None:
        try:
            await self._tick_loop(player)
        except Exception as exc:
            # A bug, not a device problem. Pause and report rather than die silently.
            log.exception("playback loop failed")
            self._fail(player, OpenLocateError(ErrorCode.INTERNAL, type(exc).__name__))

    async def _tick_loop(self, player: Player) -> None:
        while True:
            await self._sleep(self._tick_seconds)
            now = self._clock()
            elapsed = min(max(now - self._last_tick, 0.0), MAX_TICK_ELAPSED_S)
            self._last_tick = now
            fix = player.advance(elapsed)
            if not await self._deliver(player, fix):
                return
            if fix.state is PlayerState.FINISHED:
                return

    async def _deliver(self, player: Player, fix: Fix) -> bool:
        """Send one fix to the device. Returns False if playback had to pause."""
        try:
            await self._backend.set_location(fix.position)
        except OpenLocateError as err:
            self._fail(player, err)
            return False
        except Exception as exc:
            log.exception("backend raised an untranslated exception")
            self._fail(player, OpenLocateError(ErrorCode.INTERNAL, type(exc).__name__))
            return False
        self._accept(fix)
        return True

    def _accept(self, fix: Fix) -> None:
        """Record a fix the device has received and report it."""
        self._last_fix = fix
        if self._on_fix is not None:
            try:
                self._on_fix(fix)
            except Exception:
                log.exception("on_fix callback failed")

    def _fail(self, player: Player, err: OpenLocateError) -> None:
        if player.state is PlayerState.PLAYING:
            player.pause()
        self.last_error = err
        log.warning("playback paused: %s", err)
        if self._on_error is not None:
            try:
                self._on_error(err)
            except Exception:
                log.exception("on_error callback failed")


def _apply(transition: Callable[[], None]) -> None:
    try:
        transition()
    except PlayerStateError as err:
        raise OpenLocateError(ErrorCode.INVALID_STATE, str(err)) from err
