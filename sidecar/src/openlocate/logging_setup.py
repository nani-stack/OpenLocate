"""Logging to a rotating file and to stderr. Never to stdout: stdout carries the protocol."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE_NAME = "sidecar.log"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def default_log_dir(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Per-user log directory, following each OS's convention.

    The arguments exist so tests can check every platform from any platform.
    """
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home

    if platform == "win32":
        local_app_data = env.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / "OpenLocate" / "logs"
    if platform == "darwin":
        return home / "Library" / "Logs" / "OpenLocate"
    state_home = env.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else home / ".local" / "state"
    return base / "openlocate" / "logs"


def configure_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """Send all log records to a rotating file and to stderr. Returns the log file path.

    Safe to call more than once: handlers added by an earlier call are replaced.
    Raises OSError if the log directory cannot be created.
    """
    directory = default_log_dir() if log_dir is None else log_dir
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / LOG_FILE_NAME

    formatter = logging.Formatter(_FORMAT)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    stderr_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, stderr_handler):
        handler.setFormatter(formatter)
        handler.set_name("openlocate")

    root = logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == "openlocate"]:
        root.removeHandler(old)
        old.close()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)
    root.setLevel(level)
    return log_file
