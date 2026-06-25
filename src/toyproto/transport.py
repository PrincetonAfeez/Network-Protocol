"""Thin socket transport: exact reads, sendall, timeout conversion."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable

from .constants import (
    BODY_TIMEOUT,
    HEADER_SIZE,
    HEADER_TIMEOUT,
    MAX_FRAME_SECONDS,
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
)
from .errors import ConnectionClosed, TransportTimeout
from .framing import parse_header, verify_frame
from .types import Frame

RawFrameHook = Callable[[str, bytes], None]


def read_exact(
    sock: socket.socket,
    size: int,
    *,
    phase: str = "frame",
    timeout: float | None = None,
    deadline: float | None = None,
) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        if deadline is not None:
            # Shrink each recv timeout to the remaining total budget so a peer
            # dribbling bytes under the per-recv timeout still hits the deadline.
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TransportTimeout(f"frame read deadline exceeded while reading {phase}")
            sock.settimeout(budget if timeout is None else min(timeout, budget))
        elif timeout is not None:
            sock.settimeout(timeout)
        try:
            chunk = sock.recv(remaining)
        except socket.timeout as exc:
            raise TransportTimeout(f"timeout while reading {phase}") from exc
        except OSError as exc:
            raise ConnectionClosed(f"socket read failed: {exc}") from exc
        if not chunk:
            received = size - remaining
            if received == 0:
                raise ConnectionClosed(f"peer closed before {phase}")
            raise ConnectionClosed(
                f"peer closed mid-{phase}: received {received} of {size} bytes"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(
    sock: socket.socket,
    key: bytes,
    *,
    max_frame_size: int = MAX_FRAME_SIZE,
    header_timeout: float = HEADER_TIMEOUT,
    body_timeout: float = BODY_TIMEOUT,
    idle_timeout: float | None = None,
    max_frame_seconds: float = MAX_FRAME_SECONDS,
    supported_versions: tuple[int, ...] = (PROTOCOL_VERSION,),
    hook: RawFrameHook | None = None,
) -> Frame:
    # Wait for the first byte under the idle timeout: a connection may sit idle
    # between frames, so no total deadline applies yet.
    idle = header_timeout if idle_timeout is None else idle_timeout
    first_header_byte = read_exact(sock, 1, phase="header", timeout=idle)
    # A frame has begun. Bound the total time to assemble it so a peer dribbling
    # bytes just under the per-recv timeout cannot hold the connection (and its
    # thread) open indefinitely -- a defense the per-recv timeouts lack.
    deadline = time.monotonic() + max_frame_seconds if max_frame_seconds else None
    header = first_header_byte + read_exact(
        sock, HEADER_SIZE - 1, phase="header", timeout=header_timeout, deadline=deadline
    )
    header_frame, body_len = parse_header(
        header,
        max_frame_size=max_frame_size,
        supported_versions=supported_versions,
    )
    body = (
        read_exact(sock, body_len, phase="body", timeout=body_timeout, deadline=deadline)
        if body_len
        else b""
    )
    raw = header + body
    if hook:
        hook("IN", raw)
    return verify_frame(key, header_frame, body)


def write_frame(
    sock: socket.socket,
    data: bytes,
    *,
    hook: RawFrameHook | None = None,
) -> None:
    try:
        sock.sendall(data)
    except (socket.timeout, TimeoutError) as exc:
        raise TransportTimeout("timeout while writing frame") from exc
    except OSError as exc:
        raise ConnectionClosed(f"socket write failed: {exc}") from exc
    if hook:
        hook("OUT", data)
