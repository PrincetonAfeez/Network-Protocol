"""Fixed-header framing, validation, and HMAC verification."""

from __future__ import annotations

import struct
from dataclasses import replace

from .constants import (
    ALLOWED_FLAGS,
    HEADER_SIZE,
    HEADER_STRUCT,
    MAGIC,
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
    ZERO_HMAC,
    ErrorCode,
    MessageType,
)
from .errors import ProtocolError
from .hmac_auth import compute_tag, verify_tag
from .types import Frame


def _pack_header(
    version: int,
    message_type: MessageType,
    flags: int,
    request_id: int,
    body_len: int,
    tag: bytes,
) -> bytes:
    try:
        return HEADER_STRUCT.pack(
            MAGIC,
            version,
            int(message_type),
            flags,
            request_id,
            body_len,
            tag,
        )
    except struct.error as exc:
        raise ProtocolError(ErrorCode.MALFORMED_BODY, f"invalid header field: {exc}") from exc


def canonical_bytes(
    version: int,
    message_type: MessageType,
    flags: int,
    request_id: int,
    body: bytes,
) -> bytes:
    return _pack_header(version, message_type, flags, request_id, len(body), ZERO_HMAC) + body


def encode_frame(
    key: bytes,
    message_type: MessageType,
    request_id: int,
    body: bytes,
    *,
    version: int = PROTOCOL_VERSION,
    flags: int = 0,
    max_frame_size: int = MAX_FRAME_SIZE,
) -> bytes:
    if len(body) > max_frame_size:
        raise ProtocolError(
            ErrorCode.FRAME_TOO_LARGE,
            f"body length {len(body)} exceeds limit {max_frame_size}",
            fatal=True,
        )
    if flags & ~ALLOWED_FLAGS:
        raise ProtocolError(ErrorCode.ILLEGAL_FLAGS, f"unsupported flags: 0x{flags:04x}", fatal=True)
    canonical = canonical_bytes(version, message_type, flags, request_id, body)
    tag = compute_tag(key, canonical)
    return _pack_header(version, message_type, flags, request_id, len(body), tag) + body


def parse_header(
    header: bytes,
    *,
    max_frame_size: int = MAX_FRAME_SIZE,
    supported_versions: tuple[int, ...] = (PROTOCOL_VERSION,),
) -> tuple[Frame, int]:
    if len(header) != HEADER_SIZE:
        raise ProtocolError(
            ErrorCode.TRUNCATED_FRAME,
            f"header is {len(header)} bytes; expected {HEADER_SIZE}",
            fatal=True,
        )
    try:
        magic, version, raw_type, flags, request_id, body_len, tag = HEADER_STRUCT.unpack(header)
    except struct.error as exc:
        raise ProtocolError(ErrorCode.TRUNCATED_FRAME, f"cannot unpack header: {exc}", fatal=True) from exc

    if magic != MAGIC:
        raise ProtocolError(ErrorCode.BAD_MAGIC, f"expected {MAGIC!r}, got {magic!r}", fatal=True)
    if version not in supported_versions:
        raise ProtocolError(
            ErrorCode.UNSUPPORTED_VERSION,
            f"unsupported frame version {version}; supported: {supported_versions}",
            fatal=True,
        )
    try:
        message_type = MessageType(raw_type)
    except ValueError as exc:
        raise ProtocolError(
            ErrorCode.UNKNOWN_MESSAGE_TYPE,
            f"unknown message type opcode 0x{raw_type:02x}",
            fatal=True,
        ) from exc
    if flags & ~ALLOWED_FLAGS:
        raise ProtocolError(ErrorCode.ILLEGAL_FLAGS, f"unsupported flags: 0x{flags:04x}", fatal=True)
    if body_len > max_frame_size:
        raise ProtocolError(
            ErrorCode.FRAME_TOO_LARGE,
            f"declared body length {body_len} exceeds limit {max_frame_size}",
            fatal=True,
        )
    # The 32s struct field always yields exactly HMAC_SIZE bytes, so the tag
    # length needs no separate check here; verify_tag re-checks defensively.
    return Frame(version, message_type, flags, request_id, b"", tag), body_len


def verify_frame(key: bytes, header_frame: Frame, body: bytes) -> Frame:
    canonical = canonical_bytes(
        header_frame.version,
        header_frame.message_type,
        header_frame.flags,
        header_frame.request_id,
        body,
    )
    if not verify_tag(key, canonical, header_frame.hmac_tag):
        raise ProtocolError(ErrorCode.BAD_HMAC, "frame authentication failed", fatal=True)
    return replace(header_frame, body=body)


def parse_frame_bytes(
    data: bytes,
    key: bytes,
    *,
    max_frame_size: int = MAX_FRAME_SIZE,
    supported_versions: tuple[int, ...] = (PROTOCOL_VERSION,),
) -> Frame:
    if len(data) < HEADER_SIZE:
        raise ProtocolError(
            ErrorCode.TRUNCATED_FRAME,
            f"truncated header: got {len(data)} of {HEADER_SIZE} bytes",
            fatal=True,
        )
    header_frame, body_len = parse_header(
        data[:HEADER_SIZE],
        max_frame_size=max_frame_size,
        supported_versions=supported_versions,
    )
    expected = HEADER_SIZE + body_len
    if len(data) < expected:
        raise ProtocolError(
            ErrorCode.TRUNCATED_FRAME,
            f"truncated body: got {len(data) - HEADER_SIZE} of {body_len} bytes",
            fatal=True,
        )
    if len(data) > expected:
        raise ProtocolError(
            ErrorCode.TRUNCATED_FRAME,
            f"frame has {len(data) - expected} trailing bytes",
            fatal=True,
        )
    return verify_frame(key, header_frame, data[HEADER_SIZE:])
