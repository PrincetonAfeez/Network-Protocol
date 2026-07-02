"""Errors: canonical ToyProto exception hierarchy."""

from __future__ import annotations

from toyproto.constants import ErrorCode, FATAL_ERROR_CODES
from toyproto.errors import ConnectionClosed, ProtocolError, ToyProtoError, TransportTimeout


def test_protocol_error_str_includes_code_name() -> None:
    exc = ProtocolError(ErrorCode.BAD_STATE, "wrong order", fatal=False)
    assert str(exc) == "BAD_STATE: wrong order"
    assert exc.code is ErrorCode.BAD_STATE
    assert exc.reason == "wrong order"
    assert exc.fatal is False


def test_protocol_error_fatal_defaults_from_code_set() -> None:
    assert ProtocolError(ErrorCode.BAD_HMAC, "nope").fatal is True
    assert ErrorCode.BAD_HMAC in FATAL_ERROR_CODES
    assert ProtocolError(ErrorCode.NOT_FOUND, "missing", fatal=False).fatal is False


def test_protocol_error_fatal_override() -> None:
    exc = ProtocolError(ErrorCode.NOT_FOUND, "missing", fatal=True)
    assert exc.fatal is True


def test_connection_closed_is_toyproto_error() -> None:
    exc = ConnectionClosed("peer gone")
    assert isinstance(exc, ToyProtoError)
    assert str(exc) == "peer gone"


def test_transport_timeout_is_fatal_protocol_error() -> None:
    exc = TransportTimeout("slow peer")
    assert exc.code is ErrorCode.TIMEOUT
    assert exc.fatal is True
    assert str(exc) == "TIMEOUT: slow peer"


def test_transport_timeout_default_message() -> None:
    assert str(TransportTimeout()) == "TIMEOUT: network read timed out"
