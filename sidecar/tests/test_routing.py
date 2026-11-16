"""Road routing: the OSRM client, its cache and rate limiter, and playback.loadRoute."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import FakeRouter, FakeTime, Sidecar, settle
from openlocate.device.mock import MOCK_DEVICE_ID, MockDevice
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.net import HttpError, RateLimiter, check_http_url
from openlocate.routing import MAX_WAYPOINTS, Profile, RoadRoute
from openlocate.routing.cache import RouteCache, default_cache_dir
from openlocate.routing.osrm import DEFAULT_SERVERS, OsrmRouter, parse_route, servers_from_env

EIFFEL = LatLon(48.8584, 2.2945)
ARC = LatLon(48.8738, 2.2950)


def osrm_reply(coordinates: list[list[float]], distance: float = 2248.9, duration: float = 1799.2):
    return json.dumps(
        {
            "code": "Ok",
            "routes": [
                {
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "distance": distance,
                    "duration": duration,
                }
            ],
        }
    ).encode()


GOOD = osrm_reply([[2.2945, 48.8584], [2.2893, 48.8616], [2.2950, 48.8738]])


class FakeFetch:
    def __init__(self, reply: bytes | HttpError) -> None:
        self.reply = reply
        self.urls: list[str] = []

    async def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if isinstance(self.reply, HttpError):
            raise self.reply
        return self.reply


# --- parsing ----------------------------------------------------------------------------


def test_parse_route_swaps_longitude_and_latitude() -> None:
    route = parse_route(GOOD)
    assert route.points[0] == EIFFEL
    assert route.points[-1] == ARC
    assert route.distance_m == 2248.9
    assert route.average_speed_mps == pytest.approx(1.25, abs=0.01)  # 4.5 km/h, walking


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"not json", ErrorCode.ROUTING_UNAVAILABLE),
        (b"[]", ErrorCode.ROUTING_UNAVAILABLE),
        (b'{"code": "NoRoute"}', ErrorCode.NO_ROUTE_FOUND),
        (b'{"code": "NoSegment"}', ErrorCode.NO_ROUTE_FOUND),
        (b'{"code": "InvalidQuery"}', ErrorCode.ROUTING_UNAVAILABLE),
        (b'{"code": "Ok", "routes": []}', ErrorCode.ROUTING_UNAVAILABLE),
        (osrm_reply([[2.0, 48.0], [2.0, 48.0]]), ErrorCode.NO_ROUTE_FOUND),
        (osrm_reply([[2.0, 48.0], [2.1, 48.0]], distance=0), ErrorCode.NO_ROUTE_FOUND),
        (osrm_reply([[2.0, 48.0], [2.1, 48.0]], duration=0), ErrorCode.ROUTING_UNAVAILABLE),
        (osrm_reply([[2.0, 948.0], [2.1, 48.0]]), ErrorCode.ROUTING_UNAVAILABLE),
    ],
)
def test_parse_route_failures(body: bytes, code: ErrorCode) -> None:
    with pytest.raises(OpenLocateError) as caught:
        parse_route(body)
    assert caught.value.code is code


# --- the client -------------------------------------------------------------------------


async def test_each_profile_uses_its_own_server() -> None:
    fetch = FakeFetch(GOOD)
    router = OsrmRouter(limiter=RateLimiter(0), fetch=fetch)
    for profile in Profile:
        await router.route([EIFFEL, ARC], profile)
    assert [url.split("/route/")[0] for url in fetch.urls] == [DEFAULT_SERVERS[p] for p in Profile]
    assert fetch.urls[0].endswith(
        "/route/v1/driving/2.294500,48.858400;2.295000,48.873800?overview=full&geometries=geojson"
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (HttpError(None, "URLError: no network"), ErrorCode.ROUTING_UNAVAILABLE),
        (HttpError(500, "Internal Server Error"), ErrorCode.ROUTING_UNAVAILABLE),
        (HttpError(429, "Too Many Requests"), ErrorCode.ROUTING_UNAVAILABLE),
        (HttpError(400, "Bad Request", b'{"code": "NoRoute"}'), ErrorCode.NO_ROUTE_FOUND),
        (HttpError(400, "Bad Request", b'{"code": "InvalidUrl"}'), ErrorCode.ROUTING_UNAVAILABLE),
    ],
)
async def test_http_failures_become_catalogue_errors(error: HttpError, code: ErrorCode) -> None:
    router = OsrmRouter(limiter=RateLimiter(0), fetch=FakeFetch(error))
    with pytest.raises(OpenLocateError) as caught:
        await router.route([EIFFEL, ARC], Profile.DRIVE)
    assert caught.value.code is code


@pytest.mark.parametrize("count", [0, 1, MAX_WAYPOINTS + 1])
async def test_waypoint_count_is_checked_before_any_request(count: int) -> None:
    fetch = FakeFetch(GOOD)
    router = OsrmRouter(limiter=RateLimiter(0), fetch=fetch)
    with pytest.raises(OpenLocateError) as caught:
        await router.route([LatLon(0.0, i / 100) for i in range(count)], Profile.WALK)
    assert caught.value.code is ErrorCode.INVALID_PARAMS
    assert fetch.urls == []


async def test_a_repeated_route_comes_from_the_cache(tmp_path: Path) -> None:
    fetch = FakeFetch(GOOD)
    router = OsrmRouter(limiter=RateLimiter(0), cache=RouteCache(tmp_path), fetch=fetch)
    first = await router.route([EIFFEL, ARC], Profile.WALK)
    again = await router.route([EIFFEL, ARC], Profile.WALK)
    assert again == first
    assert len(fetch.urls) == 1
    await router.route([EIFFEL, ARC], Profile.BIKE)  # another profile is another route
    assert len(fetch.urls) == 2


async def test_failures_are_not_cached(tmp_path: Path) -> None:
    fetch = FakeFetch(b'{"code": "NoRoute"}')
    router = OsrmRouter(limiter=RateLimiter(0), cache=RouteCache(tmp_path), fetch=fetch)
    for _ in range(2):
        with pytest.raises(OpenLocateError):
            await router.route([EIFFEL, ARC], Profile.WALK)
    assert len(fetch.urls) == 2


# --- cache ------------------------------------------------------------------------------


def test_cache_round_trip_and_damage(tmp_path: Path) -> None:
    cache = RouteCache(tmp_path)
    route = RoadRoute((EIFFEL, ARC), 1700.0, 1300.0)
    assert cache.get("k") is None
    cache.put("k", route)
    assert cache.get("k") == route
    (entry,) = (tmp_path / "routes").glob("*.json")
    entry.write_text("{ broken", encoding="utf-8")
    assert cache.get("k") is None


def test_cache_keeps_only_the_newest_entries(tmp_path: Path) -> None:
    cache = RouteCache(tmp_path, max_entries=3)
    for index in range(6):
        cache.put(f"k{index}", RoadRoute((EIFFEL, ARC), 1.0 + index, 1.0))
    assert len(list((tmp_path / "routes").glob("*.json"))) == 3


def test_default_cache_dir_per_platform(tmp_path: Path) -> None:
    assert default_cache_dir("win32", {"LOCALAPPDATA": "L"}, tmp_path) == Path("L/OpenLocate/cache")
    assert default_cache_dir("darwin", {}, tmp_path) == tmp_path / "Library/Caches/OpenLocate"
    assert default_cache_dir("linux", {}, tmp_path) == tmp_path / ".cache/openlocate"
    assert default_cache_dir("linux", {"XDG_CACHE_HOME": "X"}, tmp_path) == Path("X/openlocate")


# --- settings and limiter ---------------------------------------------------------------


def test_servers_can_be_replaced_through_the_environment() -> None:
    servers = servers_from_env(
        {
            "OPENLOCATE_ROUTER_WALK_URL": "http://localhost:5000/",
            "OPENLOCATE_ROUTER_BIKE_URL": "ftp://nope",
        }
    )
    assert servers[Profile.WALK] == "http://localhost:5000"
    assert servers[Profile.BIKE] == DEFAULT_SERVERS[Profile.BIKE]
    assert servers[Profile.DRIVE] == DEFAULT_SERVERS[Profile.DRIVE]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x", "localhost:5000", ""])
def test_only_http_addresses_are_accepted(url: str) -> None:
    with pytest.raises(ValueError):
        check_http_url(url)


async def test_rate_limiter_spaces_requests_one_second_apart() -> None:
    time = FakeTime()
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        time.now += seconds

    limiter = RateLimiter(1.0, clock=time.clock, sleep=sleep)
    await limiter.acquire()  # the first one goes straight through
    await limiter.acquire()
    time.now += 0.4
    await limiter.acquire()
    time.now += 5.0
    await limiter.acquire()  # long after the last one: no wait
    assert waits == pytest.approx([1.0, 0.6])


# --- playback.loadRoute -----------------------------------------------------------------

WAYPOINTS = [[48.8584, 2.2945], [48.8738, 2.2950]]


async def test_load_route_plays_at_the_routers_average_speed() -> None:
    sidecar = Sidecar(MockDevice())
    try:
        await sidecar.result("device.connect", {"id": MOCK_DEVICE_ID})
        loaded = await sidecar.result(
            "playback.loadRoute", {"waypoints": WAYPOINTS, "profile": "walk"}
        )
        assert sidecar.router.calls == [([EIFFEL, ARC], Profile.WALK)]
        assert loaded["points"] == 3
        assert loaded["path"][0] == [EIFFEL.lat, EIFFEL.lon]
        assert loaded["path"][-1] == [ARC.lat, ARC.lon]
        assert len(loaded["path"]) == 3
        assert loaded["speedKmh"] == pytest.approx(5.4)  # 3000 m in 2000 s
        assert loaded["durationS"] == pytest.approx(loaded["lengthM"] / 1.5)

        status = await sidecar.result("playback.start")
        assert status["state"] == "playing"
        assert status["speedKmh"] == pytest.approx(5.4)
        await settle()
        await sidecar.time.ticks(3)
        # The device is fed points along the routed path, not the straight line.
        sent = [point for _, point in sidecar.device.history if point is not None]
        assert sent[0] == EIFFEL
        assert all(point.lon >= EIFFEL.lon for point in sent)
        assert sent[-1] != EIFFEL
    finally:
        await sidecar.close()


async def test_load_route_with_a_chosen_speed() -> None:
    sidecar = Sidecar(MockDevice())
    try:
        loaded = await sidecar.result(
            "playback.loadRoute", {"waypoints": WAYPOINTS, "profile": "drive", "speedKmh": 36}
        )
        assert loaded["speedKmh"] == pytest.approx(36)
        assert loaded["durationS"] == pytest.approx(loaded["lengthM"] / 10)
    finally:
        await sidecar.close()


@pytest.mark.parametrize(
    "params",
    [
        {"waypoints": WAYPOINTS},
        {"waypoints": WAYPOINTS, "profile": "fly"},
        {"waypoints": WAYPOINTS[:1], "profile": "walk"},
        {"waypoints": [[0, 0]] * (MAX_WAYPOINTS + 1), "profile": "walk"},
        {"waypoints": [[91, 0], [0, 0]], "profile": "walk"},
        {"waypoints": WAYPOINTS, "profile": "walk", "speedKmh": 0},
        {"waypoints": WAYPOINTS, "profile": "walk", "extra": 1},
    ],
)
async def test_load_route_rejects_bad_parameters(params: dict[str, object]) -> None:
    sidecar = Sidecar(MockDevice())
    try:
        assert await sidecar.error("playback.loadRoute", params) == (-32602, "INVALID_PARAMS")
        assert sidecar.router.calls == []
    finally:
        await sidecar.close()


@pytest.mark.parametrize("code", [ErrorCode.NO_ROUTE_FOUND, ErrorCode.ROUTING_UNAVAILABLE])
async def test_a_routing_failure_keeps_the_loaded_route(code: ErrorCode) -> None:
    sidecar = Sidecar(MockDevice(), FakeRouter(OpenLocateError(code, "nope")))
    try:
        await sidecar.result("playback.load", {"points": WAYPOINTS, "speedKmh": 10})
        before = await sidecar.result("playback.status")
        assert await sidecar.error(
            "playback.loadRoute", {"waypoints": WAYPOINTS, "profile": "bike"}
        ) == (-32000, code.value)
        assert await sidecar.result("playback.status") == before
    finally:
        await sidecar.close()
