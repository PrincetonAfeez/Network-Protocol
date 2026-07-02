"""Constants: shared constants for ToyProto."""

from __future__ import annotations

from toyproto.constants import (
    APPLICATION_ERROR_CODES,
    FATAL_ERROR_CODES,
    HEADER_SIZE,
    HEADER_STRUCT,
    MAGIC,
    MAX_CONNECTIONS,
    MAX_FRAME_SIZE,
    MAX_KV_KEYS,
    Command,
    ErrorCode,
    MessageType,
)


def test_wire_header_layout() -> None:
    assert MAGIC == b"TP01"
    assert HEADER_STRUCT.size == HEADER_SIZE == 52
    assert MAX_FRAME_SIZE == 1024 * 1024
    assert MAX_CONNECTIONS == 64
    assert MAX_KV_KEYS == 1024


def test_message_and_command_opcodes_are_unique() -> None:
    assert len(set(MessageType)) == len(MessageType)
    assert len(set(Command)) == len(Command)


def test_fatal_and_application_error_sets_do_not_overlap() -> None:
    assert not FATAL_ERROR_CODES & APPLICATION_ERROR_CODES
    assert ErrorCode.NOT_FOUND in APPLICATION_ERROR_CODES
    assert ErrorCode.STORE_FULL in APPLICATION_ERROR_CODES
    assert ErrorCode.BAD_HMAC in FATAL_ERROR_CODES
