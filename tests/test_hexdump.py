"""Hexdump: hex-dump utility for ToyProto frames."""

from __future__ import annotations

from toyproto.constants import HEADER_SIZE
from toyproto.framing import encode_frame
from toyproto.hexdump import describe_raw_frame, hex_lines
from toyproto.types import Ping

KEY = b"hex-key"


def test_hex_lines_formats_bytes() -> None:
    output = hex_lines(b"\x00\x41\x7f")
    assert "00000000" in output
    assert "41" in output
    assert "|" in output


def test_hex_lines_empty_input() -> None:
    assert hex_lines(b"") == ""


def test_describe_raw_frame_truncated_header() -> None:
    output = describe_raw_frame(b"TP")
    assert "truncated header" in output
    assert f"2/{HEADER_SIZE}" in output


def test_describe_raw_frame_full_header() -> None:
    from toyproto.codec import encode_message

    message_type, body = encode_message(Ping(5))
    raw = encode_frame(KEY, message_type, 0, body)
    output = describe_raw_frame(raw)
    assert "magic:      b'TP01'" in output
    assert "type:       0x03" in output
    assert "body:" in output
    assert "00000000" in output
