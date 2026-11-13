import pytest

from openlocate.errors import ErrorCode, OpenLocateError
from openlocate.rpc import protocol
from openlocate.rpc.protocol import ProtocolError, parse_request


def test_parses_a_request() -> None:
    request = parse_request(b'{"jsonrpc":"2.0","id":7,"method":"app.info"}')
    assert request.method == "app.info"
    assert request.id == 7
    assert request.params == {}
    assert not request.is_notification


def test_a_message_without_id_is_a_notification() -> None:
    request = parse_request(b'{"jsonrpc":"2.0","method":"x","params":{"a":1}}')
    assert request.is_notification
    assert request.params == {"a": 1}


@pytest.mark.parametrize("line", [b"{not json", b'{"a":NaN}', b"\xff\xfe", b'{"jsonrpc":"2.0",'])
def test_parse_errors(line: bytes) -> None:
    with pytest.raises(ProtocolError) as info:
        parse_request(line)
    assert info.value.rpc_code == protocol.PARSE_ERROR
    assert info.value.error.code is ErrorCode.INTERNAL


@pytest.mark.parametrize(
    ("line", "expected_id"),
    [
        (b"[]", None),
        (b'[{"jsonrpc":"2.0","id":1,"method":"a"}]', None),
        (b"42", None),
        (b'{"id":3,"method":"a"}', 3),
        (b'{"jsonrpc":"1.0","id":"x","method":"a"}', "x"),
        (b'{"jsonrpc":"2.0","id":4,"method":""}', 4),
        (b'{"jsonrpc":"2.0","id":5,"method":7}', 5),
        (b'{"jsonrpc":"2.0","id":6,"method":"a","params":"no"}', 6),
        (b'{"jsonrpc":"2.0","id":true,"method":"a"}', None),
        (b'{"jsonrpc":"2.0","id":{},"method":"a"}', None),
    ],
)
def test_invalid_requests(line: bytes, expected_id: object) -> None:
    with pytest.raises(ProtocolError) as info:
        parse_request(line)
    assert info.value.rpc_code == protocol.INVALID_REQUEST
    assert info.value.request_id == expected_id


def test_error_from_open_locate_error() -> None:
    err = OpenLocateError(ErrorCode.NOT_CONNECTED)
    response = protocol.error_from_exception(1, err)
    assert response["error"]["code"] == protocol.APPLICATION_ERROR
    assert response["error"]["data"] == err.to_dict()


def test_invalid_params_maps_to_32602() -> None:
    response = protocol.error_from_exception(1, OpenLocateError(ErrorCode.INVALID_PARAMS, "x"))
    assert response["error"]["code"] == protocol.INVALID_PARAMS


def test_other_exceptions_become_internal_without_details() -> None:
    response = protocol.error_from_exception(2, RuntimeError("secret path /home/x"))
    assert response["error"]["code"] == protocol.INTERNAL_ERROR
    assert response["error"]["data"]["code"] == "INTERNAL"
    assert "secret" not in protocol.encode(response).decode()


def test_encode_is_one_strict_json_line() -> None:
    line = protocol.encode(protocol.notification("a", {"text": "line\nbreak", "city": "Zürich"}))
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    with pytest.raises(ValueError):
        protocol.encode({"bad": float("nan")})
