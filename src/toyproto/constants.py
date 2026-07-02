"""Single source of truth for ToyProto wire constants."""

from __future__ import annotations

import struct
from enum import IntEnum

MAGIC = b"TP01"
PROTOCOL_VERSION = 1
SUPPORTED_VERSIONS = (PROTOCOL_VERSION,)

# MAGIC, VERSION, TYPE, FLAGS, REQUEST_ID, BODY_LEN, HMAC_TAG
HEADER_FORMAT = "!4sBBHQI32s"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size
HMAC_SIZE = 32
ZERO_HMAC = b"\x00" * HMAC_SIZE

MAX_FRAME_SIZE = 1024 * 1024
HEADER_TIMEOUT = 5.0
BODY_TIMEOUT = 5.0
IDLE_TIMEOUT = 60.0
# Total wall-clock budget to assemble one frame once its first byte arrives.
# Bounds slow-read ("dribble") peers that stay under the per-recv timeout.
MAX_FRAME_SECONDS = 30.0
MAX_MALFORMED_FRAMES = 1
# Upper bound on concurrently handled connections (thread-per-connection cap).
MAX_CONNECTIONS = 64
# Upper bound on distinct keys held by the in-memory key-value store.
MAX_KV_KEYS = 1024
ALLOWED_FLAGS = 0
CONTROL_REQUEST_ID = 0


class MessageType(IntEnum):
    HELLO = 0x01
    HELLO_ACK = 0x02
    PING = 0x03
    PONG = 0x04
    REQUEST = 0x05
    RESPONSE = 0x06
    ERROR = 0x07
    BYE = 0x08


class Command(IntEnum):
    ECHO = 0x01
    TIME = 0x02
    KV_PUT = 0x03
    KV_GET = 0x04
    KV_DELETE = 0x05


class ErrorCode(IntEnum):
    BAD_MAGIC = 0x0001
    UNSUPPORTED_VERSION = 0x0002
    BAD_HMAC = 0x0003
    FRAME_TOO_LARGE = 0x0004
    MALFORMED_BODY = 0x0005
    BAD_STATE = 0x0006
    UNKNOWN_MESSAGE_TYPE = 0x0007
    UNKNOWN_COMMAND = 0x0008
    TIMEOUT = 0x0009
    INTERNAL_ERROR = 0x000A
    ILLEGAL_FLAGS = 0x000B
    NOT_FOUND = 0x000C
    TRUNCATED_FRAME = 0x000D
    STORE_FULL = 0x000E


FATAL_ERROR_CODES = frozenset(
    {
        ErrorCode.BAD_MAGIC,
        ErrorCode.BAD_HMAC,
        ErrorCode.FRAME_TOO_LARGE,
        ErrorCode.UNSUPPORTED_VERSION,
        ErrorCode.UNKNOWN_MESSAGE_TYPE,
        ErrorCode.ILLEGAL_FLAGS,
        ErrorCode.TIMEOUT,
        ErrorCode.TRUNCATED_FRAME,
    }
)

# Application-level ERROR codes that do not close the connection.
APPLICATION_ERROR_CODES = frozenset(
    {
        ErrorCode.NOT_FOUND,
        ErrorCode.STORE_FULL,
    }
)
