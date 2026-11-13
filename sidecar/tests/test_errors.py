from openlocate.errors import CATALOGUE, ErrorCode, OpenLocateError


def test_every_code_has_a_message_and_a_fix() -> None:
    for code in ErrorCode:
        info = CATALOGUE[code]
        assert info.message.strip(), code
        assert info.fix.strip(), code


def test_to_dict_carries_code_message_fix_and_detail() -> None:
    err = OpenLocateError(ErrorCode.DEVELOPER_MODE_OFF, "seen on connect")
    assert err.to_dict() == {
        "code": "DEVELOPER_MODE_OFF",
        "message": "Developer Mode is turned off on the iPhone.",
        "fix": (
            "On the iPhone open Settings → Privacy & Security → Developer Mode, "
            "turn it on, then restart when asked."
        ),
        "detail": "seen on connect",
    }


def test_detail_defaults_to_none_and_str_is_readable() -> None:
    err = OpenLocateError(ErrorCode.NOT_CONNECTED)
    assert err.to_dict()["detail"] is None
    assert "NOT_CONNECTED" in str(err)
