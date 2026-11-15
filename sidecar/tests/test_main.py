"""The entry point, including one end-to-end run as a real subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openlocate import __main__ as entry


def test_backend_is_chosen_by_name() -> None:
    from openlocate.device.ios import IosDevice
    from openlocate.device.mock import MockDevice

    assert isinstance(entry._make_backend("mock"), MockDevice)
    assert isinstance(entry._make_backend("ios"), IosDevice)


def test_unknown_backend_in_the_environment_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENLOCATE_BACKEND", "banana")
    assert entry.main([]) == 2
    captured = capsys.readouterr()
    assert "unknown backend" in captured.err
    assert captured.out == ""


def run_sidecar(
    args: list[str], stdin: bytes, tmp_path: Path
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env.pop("OPENLOCATE_BACKEND", None)
    return subprocess.run(
        [sys.executable, "-m", "openlocate", *args, "--log-dir", str(tmp_path)],
        input=stdin,
        capture_output=True,
        timeout=30,
        env=env,
        check=False,
    )


def test_end_to_end_subprocess(tmp_path: Path) -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "app.info"},
        {"jsonrpc": "2.0", "id": 2, "method": "device.connect", "params": {"id": "MOCK-0001"}},
        {"jsonrpc": "2.0", "id": 3, "method": "location.set", "params": {"lat": 1.5, "lon": 2.5}},
    ]
    stdin = b"".join(json.dumps(r).encode() + b"\n" for r in requests)

    # Closing stdin (end of input) must make the sidecar exit by itself.
    result = run_sidecar(["--backend", "mock"], stdin, tmp_path)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    lines = result.stdout.splitlines()
    messages = [json.loads(line) for line in lines]  # stdout holds nothing but JSON lines
    responses = {m["id"]: m for m in messages if "id" in m}
    assert responses[1]["result"]["backend"] == "mock"
    assert Path(responses[1]["result"]["logFile"]).parent == tmp_path
    assert responses[2]["result"]["state"] == "ready"
    assert responses[3]["result"] == {}
    notifications = [m for m in messages if "id" not in m]
    assert notifications == [
        {
            "jsonrpc": "2.0",
            "method": "location.updated",
            "params": {"lat": 1.5, "lon": 2.5, "source": "teleport"},
        }
    ]
    assert "location.set" not in result.stdout.decode()  # requests are not echoed
    assert (tmp_path / "sidecar.log").exists()


def test_end_to_end_ios_is_the_default_and_starts_without_a_phone(tmp_path: Path) -> None:
    stdin = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "app.info"}).encode() + b"\n"
    result = run_sidecar([], stdin, tmp_path)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    (line,) = result.stdout.splitlines()
    assert json.loads(line)["result"]["backend"] == "ios"
