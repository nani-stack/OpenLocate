"""Routing through OSRM servers (https://project-osrm.org), one server address per profile.

The well-known demo server router.project-osrm.org only routes for cars, whatever profile is
asked for (checked 2026-11-15). The FOSSGIS servers used by openstreetmap.org run a separate
OSRM for walking, cycling and driving, so those are the defaults. They are a free community
service: one request a second at most, no uptime promise.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from typing import Any

from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.net import Fetch, HttpError, RateLimiter, check_http_url, fetch
from openlocate.routing import MAX_WAYPOINTS, Profile, RoadRoute
from openlocate.routing.cache import RouteCache

log = logging.getLogger(__name__)

DEFAULT_SERVERS: Mapping[Profile, str] = {
    Profile.WALK: "https://routing.openstreetmap.de/routed-foot",
    Profile.BIKE: "https://routing.openstreetmap.de/routed-bike",
    Profile.DRIVE: "https://routing.openstreetmap.de/routed-car",
}
SERVER_ENV_VARS: Mapping[Profile, str] = {
    Profile.WALK: "OPENLOCATE_ROUTER_WALK_URL",
    Profile.BIKE: "OPENLOCATE_ROUTER_BIKE_URL",
    Profile.DRIVE: "OPENLOCATE_ROUTER_DRIVE_URL",
}
_NO_ROUTE_CODES = {"NoRoute", "NoSegment"}


def servers_from_env(env: Mapping[str, str] | None = None) -> dict[Profile, str]:
    """The default servers, each replaceable through its environment variable."""
    env = os.environ if env is None else env
    servers = dict(DEFAULT_SERVERS)
    for profile, name in SERVER_ENV_VARS.items():
        value = env.get(name, "").strip()
        if not value:
            continue
        try:
            servers[profile] = check_http_url(value).rstrip("/")
        except ValueError:
            log.warning("routing: ignoring %s=%r (not an http(s) address)", name, value)
    return servers


def _unavailable(detail: str) -> OpenLocateError:
    return OpenLocateError(ErrorCode.ROUTING_UNAVAILABLE, detail)


class OsrmRouter:
    def __init__(
        self,
        servers: Mapping[Profile, str] | None = None,
        *,
        limiter: RateLimiter | None = None,
        cache: RouteCache | None = None,
        fetch: Fetch = fetch,
    ) -> None:
        self._servers = dict(DEFAULT_SERVERS if servers is None else servers)
        self._limiter = limiter if limiter is not None else RateLimiter(1.0)
        self._cache = cache
        self._fetch = fetch

    def url_for(self, waypoints: list[LatLon], profile: Profile) -> str:
        # OSRM wants longitude first. Six decimals is about 0.1 m.
        coordinates = ";".join(f"{p.lon:.6f},{p.lat:.6f}" for p in waypoints)
        base = self._servers[profile].rstrip("/")
        return f"{base}/route/v1/driving/{coordinates}?overview=full&geometries=geojson"

    async def route(self, waypoints: list[LatLon], profile: Profile) -> RoadRoute:
        if not 2 <= len(waypoints) <= MAX_WAYPOINTS:
            raise OpenLocateError(
                ErrorCode.INVALID_PARAMS,
                f"a road route needs 2 to {MAX_WAYPOINTS} waypoints, got {len(waypoints)}",
            )
        url = self.url_for(waypoints, profile)
        if self._cache is not None:
            cached = self._cache.get(url)
            if cached is not None:
                log.info(
                    "routing: %s route with %d points from the cache",
                    profile.value,
                    len(cached.points),
                )
                return cached

        await self._limiter.acquire()
        try:
            body = await self._fetch(url)
        except HttpError as err:
            raise self._from_http_error(err) from err
        route = parse_route(body)
        log.info(
            "routing: %s route, %.0f m, %.0f s, %d points",
            profile.value,
            route.distance_m,
            route.duration_s,
            len(route.points),
        )
        if self._cache is not None:
            self._cache.put(url, route)
        return route

    @staticmethod
    def _from_http_error(err: HttpError) -> OpenLocateError:
        # OSRM reports "no route" as HTTP 400 with a JSON body.
        code = _osrm_code(err.body)
        if code in _NO_ROUTE_CODES:
            return OpenLocateError(ErrorCode.NO_ROUTE_FOUND, f"the routing server said {code}")
        if err.status == 429:
            return _unavailable("the routing server is refusing requests for now (HTTP 429)")
        return _unavailable(f"{err}" + (f" ({code})" if code else ""))


def _osrm_code(body: bytes) -> str | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) else None


def parse_route(body: bytes) -> RoadRoute:
    """Turn an OSRM route response into a RoadRoute. Raises OpenLocateError."""
    try:
        data: Any = json.loads(body)
    except ValueError as err:
        raise _unavailable("the routing server sent a reply that is not JSON") from err
    if not isinstance(data, dict):
        raise _unavailable("the routing server sent an unexpected reply")
    code = data.get("code")
    if code in _NO_ROUTE_CODES:
        raise OpenLocateError(ErrorCode.NO_ROUTE_FOUND, f"the routing server said {code}")
    if code != "Ok":
        raise _unavailable(f"the routing server said {code!r}")
    try:
        first = data["routes"][0]
        distance_m = float(first["distance"])
        duration_s = float(first["duration"])
        coordinates = first["geometry"]["coordinates"]
        points = tuple(LatLon(float(lat), float(lon)) for lon, lat in coordinates)
    except (KeyError, IndexError, TypeError, ValueError) as err:
        raise _unavailable(f"the routing server's reply is missing route data: {err}") from err

    if len(set(points)) < 2 or not (math.isfinite(distance_m) and distance_m > 0):
        raise OpenLocateError(
            ErrorCode.NO_ROUTE_FOUND, "the start and the end are the same place on the road"
        )
    if not (math.isfinite(duration_s) and duration_s > 0):
        raise _unavailable("the routing server gave no travel time")
    return RoadRoute(points, distance_m, duration_s)
