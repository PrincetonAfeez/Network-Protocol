from __future__ import annotations

import os

import pytest

from toyproto.codec import decode_message, encode_message
from toyproto.constants import Command, ErrorCode, MessageType
from toyproto.errors import ProtocolError
from toyproto.types import Bye, ErrorMessage, Hello, HelloAck, Ping, Pong, Request, Response


@pytest.mark.parametrize(
    "message",
    [
        Hello((1,)),
        HelloAck(1),
        Ping(123),
        Pong(123),
        Request(Command.ECHO, ("hello",)),
        Request(Command.TIME),
        Request(Command.KV_PUT, ("key", "value")),
        Request(Command.KV_GET, ("key",)),
        Request(Command.KV_DELETE, ("key",)),
        Response(Command.ECHO, ("hello",)),
        ErrorMessage(ErrorCode.BAD_STATE, "wrong order"),
        Bye("done"),
    ],
)
def test_codec_round_trip(message: object) -> None:
    message_type, body = encode_message(message)  # type: ignore[arg-type]
    assert decode_message(message_type, body) == message


@pytest.mark.parametrize(
    ("message_type", "body"),
    [
        (MessageType.HELLO, b""),
        (MessageType.HELLO, b"\x00"),
        (MessageType.HELLO_ACK, b"\x01\x00"),
        (MessageType.PING, b"\x00" * 7),
        (MessageType.REQUEST, b"\x01\x01\x00\x01\xff"),
        (MessageType.REQUEST, b"\xff\x00"),
        (MessageType.REQUEST, b"\x01\x02\x00\x00\x00\x00"),
        (MessageType.ERROR, b"\xff\xff\x00\x00"),
        (MessageType.BYE, b"\x00\x05no"),
    ],
)
def test_malformed_bodies_raise_protocol_error(
    message_type: MessageType,
    body: bytes,
) -> None:
    with pytest.raises(ProtocolError):
        decode_message(message_type, body)


def test_encode_rejects_wrong_command_arity() -> None:
    with pytest.raises(ProtocolError):
        encode_message(Request(Command.TIME, ("unexpected",)))


@pytest.mark.parametrize("message_type", list(MessageType))
def test_decoder_never_crashes_on_random_bodies(message_type: MessageType) -> None:
    # The strongest robustness signal: random/garbage bytes fed straight into
    # the decoder must always either decode or raise a clean ProtocolError --
    # never any other exception. Unlike the framing-level fuzz, this targets
    # decode_message directly so every message schema is exercised.
    for _ in range(500):
        body = os.urandom(int.from_bytes(os.urandom(1), "big"))
        try:
            decode_message(message_type, body)
        except ProtocolError:
            pass

