from __future__ import annotations

import os

import pytest

from toyproto.codec import decode_message, encode_message
from toyproto.constants import (
    HEADER_SIZE,
    HEADER_STRUCT,
    MAGIC,
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
    ZERO_HMAC,
    ErrorCode,
    MessageType,
)
from toyproto.errors import ProtocolError
from toyproto.framing import encode_frame, parse_frame_bytes, parse_header
from toyproto.types import Ping

KEY = b"test-key"


def ping_frame() -> bytes:
    message_type, body = encode_message(Ping(99))
    return encode_frame(KEY, message_type, 0, body)


def test_header_is_exactly_52_bytes_and_big_endian() -> None:
    raw = ping_frame()
    assert HEADER_SIZE == 52
    assert raw[:4] == b"TP01"
    assert raw[4] == 1
    assert raw[5] == int(MessageType.PING)
    assert raw[6:8] == b"\x00\x00"
    assert raw[8:16] == b"\x00" * 8
    assert raw[16:20] == b"\x00\x00\x00\x08"


def test_frame_round_trip() -> None:
    frame = parse_frame_bytes(ping_frame(), KEY)
    assert frame.message_type is MessageType.PING
    assert frame.request_id == 0
    assert len(frame.body) == 8


@pytest.mark.parametrize("index", [4, 5, 8, HEADER_SIZE])
def test_tampering_header_or_body_is_rejected(index: int) -> None:
    raw = bytearray(ping_frame())
    raw[index] ^= 1
    with pytest.raises(ProtocolError):
        parse_frame_bytes(bytes(raw), KEY)


def test_wrong_key_fails_hmac() -> None:
    with pytest.raises(ProtocolError, match="BAD_HMAC"):
        parse_frame_bytes(ping_frame(), b"wrong-key")


def test_oversized_length_rejected_from_header_before_body_read() -> None:
    header = HEADER_STRUCT.pack(
        MAGIC,
        PROTOCOL_VERSION,
        int(MessageType.PING),
        0,
        0,
        MAX_FRAME_SIZE + 1,
        ZERO_HMAC,
    )
    with pytest.raises(ProtocolError) as exc:
        parse_header(header)
    assert exc.value.code is ErrorCode.FRAME_TOO_LARGE


@pytest.mark.parametrize(
    "header",
    [
        HEADER_STRUCT.pack(b"NOPE", 1, 3, 0, 0, 0, ZERO_HMAC),
        HEADER_STRUCT.pack(MAGIC, 2, 3, 0, 0, 0, ZERO_HMAC),
        HEADER_STRUCT.pack(MAGIC, 1, 0xFF, 0, 0, 0, ZERO_HMAC),
        HEADER_STRUCT.pack(MAGIC, 1, 3, 1, 0, 0, ZERO_HMAC),
    ],
)
def test_hostile_headers_fail_cleanly(header: bytes) -> None:
    with pytest.raises(ProtocolError):
        parse_header(header)


def test_truncated_and_trailing_frames_fail() -> None:
    raw = ping_frame()
    with pytest.raises(ProtocolError):
        parse_frame_bytes(raw[:10], KEY)
    with pytest.raises(ProtocolError):
        parse_frame_bytes(raw[:-1], KEY)
    with pytest.raises(ProtocolError):
        parse_frame_bytes(raw + b"x", KEY)


def test_random_garbage_never_leaks_unexpected_exception() -> None:
    for _ in range(1000):
        garbage = os.urandom(int.from_bytes(os.urandom(1), "big"))
        try:
            parse_frame_bytes(garbage, KEY)
        except ProtocolError:
            pass


def test_authenticated_frames_over_random_bodies_never_crash() -> None:
    # Raw garbage almost never has the correct magic, so the previous test
    # rarely reaches the body codec. Here we wrap random bodies in well-formed,
    # correctly-authenticated frames so parse_frame_bytes clears framing and
    # HMAC and the decoder is actually exercised on hostile bodies.
    for message_type in MessageType:
        for _ in range(200):
            body = os.urandom(int.from_bytes(os.urandom(1), "big"))
            frame = parse_frame_bytes(encode_frame(KEY, message_type, 0, body), KEY)
            try:
                decode_message(frame.message_type, frame.body)
            except ProtocolError:
                pass

