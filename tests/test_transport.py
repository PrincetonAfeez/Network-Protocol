from __future__ import annotations

import socket
import threading
import time

import pytest

from toyproto.codec import encode_message
from toyproto.constants import MessageType
from toyproto.errors import ConnectionClosed, TransportTimeout
from toyproto.framing import encode_frame
from toyproto.transport import read_frame
from toyproto.types import Ping

KEY = b"transport-key"


class ChunkSocket:
    def __init__(self, data: bytes, chunks: list[int]) -> None:
        self.data = data
        self.chunks = iter(chunks)
        self.offset = 0
        self.timeout: float | None = None

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def recv(self, requested: int) -> bytes:
        if self.offset >= len(self.data):
            return b""
        limit = next(self.chunks, requested)
        size = min(requested, limit, len(self.data) - self.offset)
        result = self.data[self.offset : self.offset + size]
        self.offset += size
        return result


class TimeoutSocket:
    def settimeout(self, value: float) -> None:
        pass

    def recv(self, requested: int) -> bytes:
        raise socket.timeout


class BodyTimeoutSocket(ChunkSocket):
    def recv(self, requested: int) -> bytes:
        if self.offset >= 52:
            raise socket.timeout
        return super().recv(requested)


def make_frame(nonce: int) -> bytes:
    message_type, body = encode_message(Ping(nonce))
    return encode_frame(KEY, message_type, 0, body)


def test_split_header_and_body_are_reassembled() -> None:
    raw = make_frame(7)
    sock = ChunkSocket(raw, [1, 2, 3, 5, 8, 13, 20, 1, 1, 2, 4])
    frame = read_frame(sock, KEY)  # type: ignore[arg-type]
    assert frame.message_type is MessageType.PING
    assert frame.body == b"\x00\x00\x00\x00\x00\x00\x00\x07"


def test_back_to_back_frames_remain_separate() -> None:
    left, right = socket.socketpair()
    try:
        right.sendall(make_frame(1) + make_frame(2))
        first = read_frame(left, KEY)
        second = read_frame(left, KEY)
        assert first.body[-1] == 1
        assert second.body[-1] == 2
    finally:
        left.close()
        right.close()


def test_timeout_is_converted_to_protocol_timeout() -> None:
    with pytest.raises(TransportTimeout):
        read_frame(TimeoutSocket(), KEY)  # type: ignore[arg-type]


def test_timeout_mid_body_is_converted_to_protocol_timeout() -> None:
    raw = make_frame(5)
    sock = BodyTimeoutSocket(raw[:52], [52])
    with pytest.raises(TransportTimeout, match="body"):
        read_frame(sock, KEY)  # type: ignore[arg-type]


def test_peer_close_mid_header_is_clean_connection_closed() -> None:
    sock = ChunkSocket(b"TP01", [4])
    with pytest.raises(ConnectionClosed, match="mid-header"):
        read_frame(sock, KEY)  # type: ignore[arg-type]


def test_total_read_deadline_drops_a_slow_dribbling_peer() -> None:
    left, right = socket.socketpair()
    frame = make_frame(7)

    def dribble() -> None:
        try:
            right.sendall(frame[:52])  # full header at once
            for byte in frame[52:]:    # then the body one byte at a time
                time.sleep(0.2)
                right.sendall(bytes([byte]))
        except OSError:
            pass

    thread = threading.Thread(target=dribble, daemon=True)
    thread.start()
    try:
        # Generous per-read timeout but a tight total budget: the dribbled body
        # cannot finish within max_frame_seconds, so the peer is dropped even
        # though no single read ever stalls for a full second.
        with pytest.raises(TransportTimeout):
            read_frame(left, KEY, header_timeout=1.0, body_timeout=1.0, max_frame_seconds=0.3)
    finally:
        left.close()
        right.close()
        thread.join(1)
