"""A small on-disk cache of routed paths, so repeating a trip costs no request."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from openlocate.engine.geo import LatLon
from openlocate.routing import RoadRoute

log = logging.getLogger(__name__)

MAX_ENTRIES = 200
_VERSION = 1


def default_cache_dir(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Per-user cache directory, following each OS's convention."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home

    if platform == "win32":
        local_app_data = env.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "OpenLocate" / "cache"
    if platform == "darwin":
        return home / "Library" / "Caches" / "OpenLocate"
    cache_home = env.get("XDG_CACHE_HOME")
    base = Path(cache_home) if cache_home else home / ".cache"
    return base / "openlocate"


class RouteCache:
    """One JSON file per route under directory/routes. Every failure is treated as a miss."""

    def __init__(self, directory: Path, max_entries: int = MAX_ENTRIES) -> None:
        self._directory = directory / "routes"
        self._max_entries = max_entries

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"

    def get(self, key: str) -> RoadRoute | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["version"] != _VERSION or data["key"] != key:
                return None
            points = tuple(LatLon(float(lat), float(lon)) for lat, lon in data["points"])
            route = RoadRoute(points, float(data["distanceM"]), float(data["durationS"]))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as err:
            log.warning("route cache: ignoring unreadable entry %s: %s", path.name, err)
            return None
        return route if len(route.points) >= 2 and route.duration_s > 0 else None

    def put(self, key: str, route: RoadRoute) -> None:
        data = {
            "version": _VERSION,
            "key": key,
            "distanceM": route.distance_m,
            "durationS": route.duration_s,
            "points": [[p.lat, p.lon] for p in route.points],
        }
        path = self._path(key)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
            self._trim()
        except OSError as err:
            log.warning("route cache: could not store a route: %s", err)

    def _trim(self) -> None:
        entries = sorted(self._directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in entries[: max(0, len(entries) - self._max_entries)]:
            old.unlink(missing_ok=True)
