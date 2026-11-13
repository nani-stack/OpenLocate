import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from openlocate.logging_setup import configure_logging, default_log_dir

HOME = Path("home") / "user"


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_windows_uses_localappdata() -> None:
    env = {"LOCALAPPDATA": str(Path("C:") / "Users" / "u" / "AppData" / "Local")}
    path = default_log_dir("win32", env, HOME)
    assert path == Path(env["LOCALAPPDATA"]) / "OpenLocate" / "logs"
    assert default_log_dir("win32", {}, HOME) == HOME / "AppData" / "Local" / "OpenLocate" / "logs"


def test_macos_uses_library_logs() -> None:
    assert default_log_dir("darwin", {}, HOME) == HOME / "Library" / "Logs" / "OpenLocate"


def test_linux_uses_xdg_state_home_or_the_fallback() -> None:
    state = Path("xdg") / "state"
    assert default_log_dir("linux", {"XDG_STATE_HOME": str(state)}, HOME) == (
        state / "openlocate" / "logs"
    )
    assert default_log_dir("linux", {}, HOME) == HOME / ".local" / "state" / "openlocate" / "logs"


def test_logs_go_to_the_file_and_stderr_never_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_file = configure_logging(tmp_path / "logs")
    logging.getLogger("openlocate.test").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_file.parent == tmp_path / "logs"
    assert "hello from the test" in log_file.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_calling_twice_does_not_duplicate_handlers(tmp_path: Path) -> None:
    configure_logging(tmp_path)
    count = len(logging.getLogger().handlers)
    configure_logging(tmp_path)
    assert len(logging.getLogger().handlers) == count
