"""Types: type annotations for ToyProto messages."""

from __future__ import annotations

from toyproto.constants import Command, ErrorCode, MessageType
from toyproto.types import (
    MESSAGE_TYPES,
    Bye,
    ErrorMessage,
    Frame,
    Hello,
    HelloAck,
    Ping,
    Pong,
    Request,
    Response,
)


def test_message_types_map_covers_all_dataclasses() -> None:
    assert MESSAGE_TYPES[Hello] is MessageType.HELLO
    assert MESSAGE_TYPES[HelloAck] is MessageType.HELLO_ACK
    assert MESSAGE_TYPES[Ping] is MessageType.PING
    assert MESSAGE_TYPES[Pong] is MessageType.PONG
    assert MESSAGE_TYPES[Request] is MessageType.REQUEST
    assert MESSAGE_TYPES[Response] is MessageType.RESPONSE
    assert MESSAGE_TYPES[ErrorMessage] is MessageType.ERROR
    assert MESSAGE_TYPES[Bye] is MessageType.BYE


def test_frame_and_message_defaults() -> None:
    frame = Frame(1, MessageType.PING, 0, 0, b"\x00" * 8, b"\x01" * 32)
    assert frame.version == 1
    assert frame.body == b"\x00" * 8
    assert Request(Command.TIME).arguments == ()
    assert Response(Command.TIME).values == ()
    assert Bye().reason == ""
    assert ErrorMessage(ErrorCode.BAD_STATE, "x").reason == "x"
