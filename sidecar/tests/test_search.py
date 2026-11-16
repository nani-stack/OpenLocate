"""Address search: the Nominatim client and the search.find method."""

from __future__ import annotations

import json

import pytest

from conftest import Sidecar
from openlocate.device.mock import MockDevice
from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.net import HttpError, RateLimiter
from openlocate.routing import RoadRoute
from openlocate.rpc.handlers import MAX_PATH_POINTS, _path_json
from openlocate.search import (
    DEFAULT_SERVER,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    NominatimGeocoder,
    Place,
    parse_places,
    server_from_env,
)

REPLY = json.dumps(
    [
        {"display_name": "Tour Eiffel, Paris, France", "lat": "48.8582599", "lon": "2.2945006"},
        {"display_name": "Eiffel Tower, Las Vegas", "lat": "36.1125", "lon": "-115.1727"},
    ]
).encode()


class FakeFetch:
    def __init__(self, reply: bytes | HttpError) -> None:
        self.reply = reply
        self.urls: list[str] = []

    async def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if isinstance(self.reply, HttpError):
            raise self.reply
        return self.reply


def test_parse_places_reads_text_coordinates() -> None:
    places = parse_places(REPLY)
    assert places[0] == Place("Tour Eiffel, Paris, France", LatLon(48.8582599, 2.2945006))
    assert len(places) == 2


def test_parse_places_skips_unusable_entries_and_caps_the_list() -> None:
    good = {"display_name": "A", "lat": "1", "lon": "2"}
    body = json.dumps([{"lat": "1"}, {"display_name": "B", "lat": "999", "lon": "0"}, "x"])
    assert parse_places(body.encode()) == []
    assert len(parse_places(json.dumps([good] * 9).encode())) == MAX_RESULTS
    assert parse_places(b"[]") == []


@pytest.mark.parametrize("body", [b"<html>", b'{"error": "nope"}'])
def test_parse_places_rejects_other_replies(body: bytes) -> None:
    with pytest.raises(OpenLocateError) as caught:
        parse_places(body)
    assert caught.value.code is ErrorCode.SEARCH_UNAVAILABLE


async def test_the_query_is_encoded_and_repeat_searches_are_cached() -> None:
    fetch = FakeFetch(REPLY)
    geocoder = NominatimGeocoder(limiter=RateLimiter(0), fetch=fetch)
    first = await geocoder.find("  10 rue de l'Université,   Paris ")
    again = await geocoder.find("10 RUE DE L'UNIVERSITÉ, PARIS")
    assert again == first
    assert fetch.urls == [
        f"{DEFAULT_SERVER}/search?q=10+rue+de+l%27Universit%C3%A9%2C+Paris&format=jsonv2&limit=5"
    ]


@pytest.mark.parametrize("query", ["", "   ", "x" * (MAX_QUERY_CHARS + 1)])
async def test_bad_queries_are_refused_before_any_request(query: str) -> None:
    fetch = FakeFetch(REPLY)
    geocoder = NominatimGeocoder(limiter=RateLimiter(0), fetch=fetch)
    with pytest.raises(OpenLocateError) as caught:
        await geocoder.find(query)
    assert caught.value.code is ErrorCode.INVALID_PARAMS
    assert fetch.urls == []


@pytest.mark.parametrize("error", [HttpError(None, "no network"), HttpError(429, "slow down")])
async def test_failures_are_reported_and_not_cached(error: HttpError) -> None:
    fetch = FakeFetch(error)
    geocoder = NominatimGeocoder(limiter=RateLimiter(0), fetch=fetch)
    for _ in range(2):
        with pytest.raises(OpenLocateError) as caught:
            await geocoder.find("Paris")
        assert caught.value.code is ErrorCode.SEARCH_UNAVAILABLE
    assert len(fetch.urls) == 2


def test_the_server_can_be_replaced_through_the_environment() -> None:
    assert server_from_env({}) == DEFAULT_SERVER
    assert server_from_env({"OPENLOCATE_SEARCH_URL": "http://localhost:8080/"}) == (
        "http://localhost:8080"
    )
    assert server_from_env({"OPENLOCATE_SEARCH_URL": "file:///x"}) == DEFAULT_SERVER


async def test_search_find_returns_places() -> None:
    sidecar = Sidecar(MockDevice())
    try:
        found = await sidecar.result("search.find", {"query": " Eiffel   Tower "})
        assert found == {"results": [{"name": "Somewhere, Paris", "lat": 48.8584, "lon": 2.2945}]}
        assert sidecar.geocoder.queries == ["Eiffel Tower"]
        sidecar.geocoder.places = []
        assert await sidecar.result("search.find", {"query": "nowhere"}) == {"results": []}
    finally:
        await sidecar.close()


@pytest.mark.parametrize("params", [{}, {"query": ""}, {"query": 5}, {"query": "a", "x": 1}])
async def test_search_find_rejects_bad_parameters(params: dict[str, object]) -> None:
    sidecar = Sidecar(MockDevice())
    try:
        assert await sidecar.error("search.find", params) == (-32602, "INVALID_PARAMS")
    finally:
        await sidecar.close()


def test_the_drawing_path_is_thinned_but_keeps_both_ends() -> None:
    points = tuple(LatLon(0.0, i / 100_000) for i in range(MAX_PATH_POINTS * 3 + 7))
    route = RoadRoute(points, 1.0, 1.0)
    path = _path_json(route.points)
    assert len(path) == MAX_PATH_POINTS
    assert path[0] == [points[0].lat, points[0].lon]
    assert path[-1] == [points[-1].lat, points[-1].lon]
    assert _path_json(points[:5]) == [[p.lat, p.lon] for p in points[:5]]
