"""Reproducibly generate known-good and hostile ToyProto frame fixtures."""

from __future__ import annotations

from pathlib import Path

from toyproto.codec import encode_message
from toyproto.constants import (
    HEADER_STRUCT,
    MAGIC,
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
    ZERO_HMAC,
    Command,
    MessageType,
)
from toyproto.framing import encode_frame
from toyproto.types import Hello, Ping, Request

KEY = b"fixture-test-key"
OUTPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "frames"


def encoded(message: object, request_id: int) -> bytes:
    message_type, body = encode_message(message)  # type: ignore[arg-type]
    return encode_frame(KEY, message_type, request_id, body)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    hello = encoded(Hello((1,)), 0)
    ping = encoded(Ping(0x0102030405060708), 0)
    request = encoded(Request(Command.ECHO, ("fixture hello",)), 42)

    fixtures = {
        "valid_hello.bin": hello,
        "valid_ping.bin": ping,
        "valid_request_echo.bin": request,
        "bad_magic.bin": b"NOPE" + hello[4:],
        "bad_hmac.bin": hello[:20] + bytes([hello[20] ^ 0xFF]) + hello[21:],
        "oversized_length.bin": HEADER_STRUCT.pack(
            MAGIC,
            PROTOCOL_VERSION,
            int(MessageType.PING),
            0,
            0,
            MAX_FRAME_SIZE + 1,
            ZERO_HMAC,
        ),
        "truncated_header.bin": hello[:17],
        "truncated_body.bin": request[:-3],
        "bad_utf8.bin": encode_frame(
            KEY,
            MessageType.REQUEST,
            43,
            b"\x01\x01\x00\x01\xff",
        ),
        "unknown_type.bin": HEADER_STRUCT.pack(
            MAGIC,
            PROTOCOL_VERSION,
            0xFF,
            0,
            0,
            0,
            ZERO_HMAC,
        ),
        "wrong_state_request.bin": request,
    }
    for name, data in fixtures.items():
        (OUTPUT / name).write_bytes(data)
    print(f"wrote {len(fixtures)} fixtures to {OUTPUT}")


if __name__ == "__main__":
    main()

