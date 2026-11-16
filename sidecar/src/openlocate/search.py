"""Address search through Nominatim (https://nominatim.org).

The public server's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
allows one request a second for the whole application, forbids search-as-you-type, and asks
for an identifying User-Agent and for results to be cached. So: every search goes through the
shared RateLimiter, the UI only searches on Enter or a button, and answers are remembered for
the life of the process.
"""

from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from openlocate.engine.geo import LatLon
from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.net import Fetch, HttpError, RateLimiter, check_http_url, fetch

log = logging.getLogger(__name__)

DEFAULT_SERVER = "https://nominatim.openstreetmap.org"
SERVER_ENV_VAR = "OPENLOCATE_SEARCH_URL"
MAX_QUERY_CHARS = 200
MAX_RESULTS = 5
CACHE_ENTRIES = 200


@dataclass(frozen=True)
class Place:
    name: str
    position: LatLon


class Geocoder(Protocol):
    async def find(self, query: str) -> list[Place]:
        """Places matching the text, best first. Raises OpenLocateError on failure."""
        ...


def server_from_env(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    value = env.get(SERVER_ENV_VAR, "").strip()
    if not value:
        return DEFAULT_SERVER
    try:
        return check_http_url(value).rstrip("/")
    except ValueError:
        log.warning("search: ignoring %s=%r (not an http(s) address)", SERVER_ENV_VAR, value)
        return DEFAULT_SERVER


def _unavailable(detail: str) -> OpenLocateError:
    return OpenLocateError(ErrorCode.SEARCH_UNAVAILABLE, detail)


def normalise_query(query: str) -> str:
    """Collapse whitespace. Raises INVALID_PARAMS for an empty or over-long query."""
    text = " ".join(query.split())
    if not text:
        raise OpenLocateError(ErrorCode.INVALID_PARAMS, "query must not be empty")
    if len(text) > MAX_QUERY_CHARS:
        raise OpenLocateError(
            ErrorCode.INVALID_PARAMS, f"query is longer than {MAX_QUERY_CHARS} characters"
        )
    return text


class NominatimGeocoder:
    def __init__(
        self,
        server: str = DEFAULT_SERVER,
        *,
        limiter: RateLimiter | None = None,
        fetch: Fetch = fetch,
    ) -> None:
        self._server = server.rstrip("/")
        self._limiter = limiter if limiter is not None else RateLimiter(1.0)
        self._fetch = fetch
        self._cache: OrderedDict[str, list[Place]] = OrderedDict()

    def url_for(self, query: str) -> str:
        parameters = urlencode({"q": query, "format": "jsonv2", "limit": MAX_RESULTS})
        return f"{self._server}/search?{parameters}"

    async def find(self, query: str) -> list[Place]:
        text = normalise_query(query)
        key = text.casefold()
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return list(cached)

        await self._limiter.acquire()
        try:
            body = await self._fetch(self.url_for(text))
        except HttpError as err:
            if err.status == 429:
                raise _unavailable("the search server is refusing requests for now") from err
            raise _unavailable(str(err)) from err
        places = parse_places(body)
        log.info("search: %d result(s)", len(places))  # the query itself is not logged
        self._cache[key] = places
        while len(self._cache) > CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return list(places)


def parse_places(body: bytes) -> list[Place]:
    try:
        data: Any = json.loads(body)
    except ValueError as err:
        raise _unavailable("the search server sent a reply that is not JSON") from err
    if not isinstance(data, list):
        raise _unavailable("the search server sent an unexpected reply")
    places: list[Place] = []
    for item in data[:MAX_RESULTS]:
        try:
            name = str(item["display_name"])
            position = LatLon(float(item["lat"]), float(item["lon"]))
        except (KeyError, TypeError, ValueError):
            continue  # skip an entry we cannot use; the rest are still good
        if name:
            places.append(Place(name, position))
    return places
