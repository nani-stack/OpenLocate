"""The JSON-RPC methods the sidecar offers, with parameter validation.

JSON names are camelCase; Python names are snake_case. Every bad parameter is reported as
OpenLocateError(INVALID_PARAMS) with a detail naming the field.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from openlocate import __version__
from openlocate.device.base import DeviceBackend, DeviceInfo
from openlocate.engine.geo import LatLon
from openlocate.engine.jitter import Jitter, JitterConfig
from openlocate.engine.player import MAX_SPEED_MPS, Fix, kmh_to_mps, mps_to_kmh
from openlocate.engine.route import Route
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.playback import PlaybackRunner, PlaybackStatus
from openlocate.routing import MAX_WAYPOINTS, Profile, Router
from openlocate.rpc.protocol import JsonObject
from openlocate.rpc.server import Handler, Notifier

log = logging.getLogger(__name__)

MAX_ROUTE_POINTS = 200_000


# --- parameter validation -------------------------------------------------------------


def _invalid(detail: str) -> OpenLocateError:
    return OpenLocateError(ErrorCode.INVALID_PARAMS, detail)


def _check_keys(
    params: JsonObject, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()
) -> None:
    missing = [key for key in required if key not in params]
    if missing:
        raise _invalid(f"missing parameter(s): {', '.join(missing)}")
    unknown = sorted(set(params) - set(required) - set(optional))
    if unknown:
        raise _invalid(f"unknown parameter(s): {', '.join(unknown)}")


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{name} must be a number")
    if not math.isfinite(value):
        raise _invalid(f"{name} must be finite")
    return float(value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{name} must be a non-empty string")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(f"{name} must be true or false")
    return value


def _lat_lon(lat: object, lon: object, name: str) -> LatLon:
    lat_value = _number(lat, f"{name} latitude")
    lon_value = _number(lon, f"{name} longitude")
    try:
        return LatLon(lat_value, lon_value)
    except ValueError as err:
        raise _invalid(f"{name}: {err}") from err


def _speed_mps(params: JsonObject) -> float:
    speed_kmh = _number(params["speedKmh"], "speedKmh")
    max_kmh = mps_to_kmh(MAX_SPEED_MPS)
    if not 0.0 < speed_kmh <= max_kmh:
        raise _invalid(f"speedKmh must be above 0 and at most {max_kmh:g}, got {speed_kmh:g}")
    return kmh_to_mps(speed_kmh)


def _route_points(
    value: object, name: str = "points", maximum: int = MAX_ROUTE_POINTS
) -> list[LatLon]:
    if not isinstance(value, list):
        raise _invalid(f"{name} must be an array of [lat, lon] pairs")
    if len(value) > maximum:
        raise _invalid(f"{name} has {len(value)} entries; the maximum is {maximum}")
    points: list[LatLon] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, list) or len(pair) != 2:
            raise _invalid(f"{name}[{index}] must be a [lat, lon] pair")
        points.append(_lat_lon(pair[0], pair[1], f"{name}[{index}]"))
    return points


def _profile(value: object) -> Profile:
    names = [profile.value for profile in Profile]
    if not isinstance(value, str) or value not in names:
        raise _invalid(f"profile must be one of: {', '.join(names)}")
    return Profile(value)


# --- JSON shapes ----------------------------------------------------------------------


def _lat_lon_json(point: LatLon | None) -> JsonObject | None:
    return None if point is None else {"lat": point.lat, "lon": point.lon}


def _device_json(info: DeviceInfo) -> JsonObject:
    return {
        "id": info.id,
        "name": info.name,
        "model": info.model,
        "osVersion": info.os_version,
        "connection": info.connection,
        "state": info.state.value,
    }


def _status_json(status: PlaybackStatus) -> JsonObject:
    return {
        "state": status["state"],
        "distanceM": status["distance_m"],
        "lengthM": status["length_m"],
        "progress": status["progress"],
        "speedKmh": mps_to_kmh(status["speed_mps"]),
        "lap": status["lap"],
        "position": _lat_lon_json(status["position"]),
    }


# --- handlers ---------------------------------------------------------------------------


class SidecarHandlers:
    """All RPC methods, bound to one device backend and one playback runner."""

    def __init__(
        self,
        backend: DeviceBackend,
        *,
        backend_name: str,
        log_file: Path | None,
        router: Router | None = None,
        tick_seconds: float = 1.0,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._backend = backend
        self._backend_name = backend_name
        self._log_file = log_file
        self._router = router
        runner_options: dict[str, Any] = {}
        if clock is not None:
            runner_options["clock"] = clock
        if sleep is not None:
            runner_options["sleep"] = sleep
        self._runner = PlaybackRunner(
            backend,
            tick_seconds=tick_seconds,
            on_fix=self._on_fix,
            on_error=self._on_error,
            **runner_options,
        )
        self._notify: Notifier | None = None
        self._pending: set[asyncio.Future[None]] = set()
        self._last_state = self._runner.status()["state"]

    @property
    def runner(self) -> PlaybackRunner:
        return self._runner

    def bind_notifier(self, notify: Notifier) -> None:
        self._notify = notify

    def methods(self) -> Mapping[str, Handler]:
        return {
            "app.info": self.app_info,
            "device.list": self.device_list,
            "device.connect": self.device_connect,
            "device.disconnect": self.device_disconnect,
            "location.set": self.location_set,
            "location.clear": self.location_clear,
            "playback.load": self.playback_load,
            "playback.loadRoute": self.playback_load_route,
            "playback.start": self.playback_start,
            "playback.pause": self.playback_pause,
            "playback.resume": self.playback_resume,
            "playback.stop": self.playback_stop,
            "playback.setSpeed": self.playback_set_speed,
            "playback.status": self.playback_status,
        }

    async def shutdown(self) -> None:
        """Stop playback and flush notifications that are still being written."""
        await self._runner.stop()
        self._emit_state_if_changed()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    # app / device

    async def app_info(self, params: JsonObject) -> JsonObject:
        _check_keys(params)
        return {
            "version": __version__,
            "backend": self._backend_name,
            "logFile": None if self._log_file is None else str(self._log_file),
        }

    async def device_list(self, params: JsonObject) -> JsonObject:
        _check_keys(params)
        devices = await self._backend.list_devices()
        return {"devices": [_device_json(d) for d in devices]}

    async def device_connect(self, params: JsonObject) -> JsonObject:
        _check_keys(params, required=("id",))
        device_id = _string(params["id"], "id")
        return _device_json(await self._backend.connect(device_id))

    async def device_disconnect(self, params: JsonObject) -> JsonObject:
        _check_keys(params)
        await self._stop_playback()
        await self._backend.disconnect()
        return {}

    # location

    async def location_set(self, params: JsonObject) -> JsonObject:
        _check_keys(params, required=("lat", "lon"))
        point = _lat_lon(params["lat"], params["lon"], "location")
        await self._stop_playback()
        await self._backend.set_location(point)
        self._post("location.updated", {"lat": point.lat, "lon": point.lon, "source": "teleport"})
        return {}

    async def location_clear(self, params: JsonObject) -> JsonObject:
        _check_keys(params)
        await self._stop_playback()
        await self._backend.clear_location()
        return {}

    # playback

    async def playback_load(self, params: JsonObject) -> JsonObject:
        _check_keys(params, required=("points", "speedKmh"), optional=("loop", "jitter"))
        points = _route_points(params["points"])
        speed_mps = _speed_mps(params)
        loop = _bool(params.get("loop", False), "loop")
        use_jitter = _bool(params.get("jitter", False), "jitter")
        try:
            route = Route(points)
        except ValueError as err:
            raise _invalid(str(err)) from err
        jitter = Jitter(JitterConfig()) if use_jitter else None
        await self._runner.load(route, speed_mps, loop=loop, jitter=jitter)
        self._emit_state_if_changed()
        return {"lengthM": route.length_m, "points": len(route.points)}

    async def playback_load_route(self, params: JsonObject) -> JsonObject:
        """Route through the waypoints along real roads, then load the result for playback.

        Without speedKmh the trip is played at the routing service's own average speed for
        that way of travelling, so it takes about as long as the real trip would.
        """
        _check_keys(
            params, required=("waypoints", "profile"), optional=("speedKmh", "loop", "jitter")
        )
        waypoints = _route_points(params["waypoints"], "waypoints", MAX_WAYPOINTS)
        if len(waypoints) < 2:
            raise _invalid(f"waypoints needs at least 2 entries, got {len(waypoints)}")
        profile = _profile(params["profile"])
        speed_mps = _speed_mps(params) if "speedKmh" in params else None
        loop = _bool(params.get("loop", False), "loop")
        use_jitter = _bool(params.get("jitter", False), "jitter")
        if self._router is None:
            raise OpenLocateError(ErrorCode.ROUTING_UNAVAILABLE, "no routing service is set up")

        road = await self._router.route(waypoints, profile)
        try:
            route = Route(road.points)
        except ValueError as err:
            raise OpenLocateError(ErrorCode.NO_ROUTE_FOUND, str(err)) from err
        if speed_mps is None:
            speed_mps = min(road.average_speed_mps, MAX_SPEED_MPS)
        jitter = Jitter(JitterConfig()) if use_jitter else None
        await self._runner.load(route, speed_mps, loop=loop, jitter=jitter)
        self._emit_state_if_changed()
        return {
            "lengthM": route.length_m,
            "points": len(route.points),
            "durationS": route.length_m / speed_mps,
            "speedKmh": mps_to_kmh(speed_mps),
        }

    async def playback_start(self, params: JsonObject) -> JsonObject:
        return await self._playback_action(params, self._runner.start)

    async def playback_pause(self, params: JsonObject) -> JsonObject:
        return await self._playback_action(params, self._runner.pause)

    async def playback_resume(self, params: JsonObject) -> JsonObject:
        return await self._playback_action(params, self._runner.resume)

    async def playback_stop(self, params: JsonObject) -> JsonObject:
        return await self._playback_action(params, self._runner.stop)

    async def playback_set_speed(self, params: JsonObject) -> JsonObject:
        _check_keys(params, required=("speedKmh",))
        await self._runner.set_speed(_speed_mps(params))
        return self._status()

    async def playback_status(self, params: JsonObject) -> JsonObject:
        _check_keys(params)
        return self._status()

    async def _playback_action(
        self, params: JsonObject, action: Callable[[], Awaitable[None]]
    ) -> JsonObject:
        _check_keys(params)
        await action()
        self._emit_state_if_changed()
        return self._status()

    async def _stop_playback(self) -> None:
        await self._runner.stop()
        self._emit_state_if_changed()

    def _status(self) -> JsonObject:
        return _status_json(self._runner.status())

    # notifications

    def _on_fix(self, fix: Fix) -> None:
        point = fix.position
        self._post("location.updated", {"lat": point.lat, "lon": point.lon, "source": "playback"})
        self._emit_state_if_changed()

    def _on_error(self, error: OpenLocateError) -> None:
        self._post("playback.error", dict(error.to_dict()))
        self._emit_state_if_changed()

    def _emit_state_if_changed(self) -> None:
        status = self._runner.status()
        if status["state"] != self._last_state:
            self._last_state = status["state"]
            self._post("playback.state", _status_json(status))

    def _post(self, method: str, params: JsonObject) -> None:
        """Send a notification without waiting for it. Order is kept by the server's lock."""
        if self._notify is None:
            return
        task = asyncio.ensure_future(self._notify(method, params))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
