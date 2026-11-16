"""Replays protocol/contract.json (shared with the app's tests) against the mock backend."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from conftest import Sidecar, settle
from openlocate.device.base import DeviceState
from openlocate.device.mock import MOCK_DEVICE_ID, MockDevice
from openlocate.engine.player import PlayerState
from openlocate.errors import ErrorCode
from openlocate.routing import Profile

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "protocol" / "contract.json"

pytestmark = pytest.mark.skipif(not CONTRACT_PATH.exists(), reason="no protocol/contract.json")


def load_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def matches(expected: Any, actual: Any) -> bool:
    """The contract's matching rules (see the $comment at the top of the file)."""
    if expected == "<string>":
        return isinstance(actual, str)
    if expected == "<number>":
        return _is_number(actual)
    if expected == "<int>":
        return isinstance(actual, int) and not isinstance(actual, bool)
    if expected == "<bool>":
        return isinstance(actual, bool)
    if expected == "<latlon>":
        return (
            isinstance(actual, dict)
            and set(actual) == {"lat", "lon"}
            and all(_is_number(v) for v in actual.values())
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(expected) == set(actual)
            and all(matches(expected[k], actual[k]) for k in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(matches(e, a) for e, a in zip(expected, actual, strict=True))
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    return bool(expected == actual)


def without_envelope(message: dict[str, Any]) -> dict[str, Any]:
    assert message["jsonrpc"] == "2.0"
    return {"method": message["method"], "params": message["params"]}


def test_enums_match_the_code() -> None:
    enums = load_contract()["enums"]
    assert enums["errorCode"] == [code.value for code in ErrorCode]
    assert enums["deviceState"] == [state.value for state in DeviceState]
    assert enums["playbackState"] == [state.value for state in PlayerState]
    assert enums["routeProfile"] == [profile.value for profile in Profile]


async def test_session_replays() -> None:
    sidecar = Sidecar(MockDevice())
    try:
        for step in load_contract()["session"]:
            sidecar.output.drain()
            already = len(sidecar.output.notifications)
            response = await sidecar.call(step["request"]["method"], step["request"].get("params"))
            await settle()
            name = step["name"]
            if "result" in step:
                assert "result" in response, (name, response)
                assert matches(step["result"], response["result"]), (name, response)
            else:
                assert "error" in response, (name, response)
                assert matches(step["error"], response["error"]["data"]), (name, response)
            sidecar.output.drain()
            emitted = [without_envelope(n) for n in sidecar.output.notifications[already:]]
            for expected in step.get("notifications", []):
                assert any(matches(expected, actual) for actual in emitted), (name, emitted)
    finally:
        await sidecar.close()


async def test_notification_shapes() -> None:
    expected_by_method = {n["method"]: n for n in load_contract()["notifications"]}
    route = {"points": [[0.0, 0.0], [0.0, 0.01]], "speedKmh": 360}

    finishing = Sidecar(MockDevice())
    try:
        await finishing.result("device.connect", {"id": MOCK_DEVICE_ID})
        await finishing.result("playback.load", route)
        await finishing.result("playback.start")
        await settle()
        await finishing.time.ticks(15)
        finishing.output.drain()
        emitted = [without_envelope(n) for n in finishing.output.notifications]
    finally:
        await finishing.close()

    failing = Sidecar(MockDevice(fail_set_after=2))
    try:
        await failing.result("device.connect", {"id": MOCK_DEVICE_ID})
        await failing.result("playback.load", route)
        await failing.result("playback.start")
        await settle()
        await failing.time.ticks(3)
        failing.output.drain()
        emitted += [without_envelope(n) for n in failing.output.notifications]
    finally:
        await failing.close()

    for method, expected in expected_by_method.items():
        assert any(matches(expected, actual) for actual in emitted), (method, emitted)
