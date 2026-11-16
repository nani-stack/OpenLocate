"""Outgoing HTTP for the search and routing clients: one rate limiter and one GET helper.

The public servers we use allow at most one request a second for the whole app, so every
client shares a single RateLimiter. Standard library only.
"""

from __future__ import annotations

import asyncio
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from openlocate import __version__

USER_AGENT = f"OpenLocate/{__version__}"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_MAX_BYTES = 32 * 1024 * 1024


class HttpError(Exception):
    """A request that did not produce a 200 response. status is None for network failures."""

    def __init__(self, status: int | None, reason: str, body: bytes = b"") -> None:
        super().__init__(f"HTTP {status}: {reason}" if status is not None else reason)
        self.status = status
        self.reason = reason
        self.body = body


class RateLimiter:
    """Spaces calls at least min_interval_s apart. Waiters are served in order."""

    def __init__(
        self,
        min_interval_s: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if min_interval_s < 0:
            raise ValueError(f"min_interval_s must be >= 0, got {min_interval_s}")
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed: float | None = None

    async def acquire(self) -> None:
        """Return when the caller may send one request."""
        async with self._lock:
            now = self._clock()
            if self._next_allowed is not None and now < self._next_allowed:
                await self._sleep(self._next_allowed - now)
                now = max(self._clock(), self._next_allowed)
            self._next_allowed = now + self._min_interval_s


def check_http_url(url: str) -> str:
    """Return url if it is a usable http(s) address, else raise ValueError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not an http(s) address: {url!r}")
    return url


def http_get(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
    user_agent: str = USER_AGENT,
) -> bytes:
    """Blocking GET. Returns the body of a 200 response; anything else raises HttpError."""
    check_http_url(url)
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url, headers={"User-Agent": user_agent, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            body: bytes = response.read(max_bytes + 1)
            status: int = response.status
    except urllib.error.HTTPError as err:
        raise HttpError(err.code, str(err.reason), err.read(64 * 1024)) from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        reason = getattr(err, "reason", None) or err
        raise HttpError(None, f"{type(err).__name__}: {reason}") from err
    if status != 200:
        raise HttpError(status, "unexpected status", body[: 64 * 1024])
    if len(body) > max_bytes:
        raise HttpError(None, f"response is larger than {max_bytes} bytes")
    return body


Fetch = Callable[[str], Awaitable[bytes]]


async def fetch(url: str) -> bytes:
    """http_get on a worker thread, so the event loop keeps ticking playback."""
    return await asyncio.to_thread(http_get, url)
