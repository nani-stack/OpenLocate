"""The entry point, including one end-to-end run as a real subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openlocate import __main__ as entry


def test_ios_backend_is_not_implemented_yet(capsys: pytest.CaptureFixture[str]) -> None:
    assert entry.main(["--backend", "ios"]) == 2
    captured = capsys.readouterr()
    assert "not implemented" in captured.err
    assert captured.out == ""


def test_default_backend_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENLOCATE_BACKEND", raising=False)
    assert entry.main([]) == 2  # defaults to ios
    monkeypatch.setenv("OPENLOCATE_BACKEND", "banana")
    assert entry.main([]) == 2
    assert "unknown backend" in capsys.readouterr().err


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


def test_end_to_end_ios_exits_with_code_2(tmp_path: Path) -> None:
    result = run_sidecar(["--backend", "ios"], b"", tmp_path)
    assert result.returncode == 2
    assert result.stdout == b""
    assert b"not implemented" in result.stderr
