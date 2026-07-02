"""Synchronous ToyProto client."""

from __future__ import annotations

import logging
import secrets
import socket
from contextlib import suppress
from typing import NoReturn

from .codec import decode_message, encode_message
from .constants import (
    APPLICATION_ERROR_CODES,
    CONTROL_REQUEST_ID,
    MAX_FRAME_SECONDS,
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    Command,
    ErrorCode,
)
from .errors import ConnectionClosed, ProtocolError, TransportTimeout
from .framing import encode_frame
from .state_machine import ConnectionState, Role, StateMachine
from .transport import RawFrameHook, read_frame, write_frame
from .types import Bye, ErrorMessage, Hello, HelloAck, Message, Ping, Pong, Request, Response

LOGGER = logging.getLogger("toyproto.client")


class ToyProtoClient:
    """Synchronous ToyProto client.

    An instance is single-use: after :meth:`close` or a failed handshake the
    connection state is ``CLOSED`` and a fresh instance is required. A TCP
    connection failure before the handshake completes leaves the instance in
    ``NEW`` and :meth:`connect` may be retried. After :meth:`close`, a failed
    handshake, or any non-recoverable protocol/transport error, the instance is
    ``CLOSED`` and cannot be reused.
    """

    def __init__(
        self,
        host: str,
        port: int,
        key: bytes,
        *,
        timeout: float = 5.0,
        max_frame_size: int = MAX_FRAME_SIZE,
        max_frame_seconds: float = MAX_FRAME_SECONDS,
        frame_hook: RawFrameHook | None = None,
    ) -> None:
        if not key:
            raise ValueError("shared key must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_frame_seconds <= 0:
            raise ValueError("max_frame_seconds must be positive")
        if max_frame_size < 1:
            raise ValueError("max_frame_size must be at least 1")
        self.host = host
        self.port = port
        self.key = key
        self.timeout = timeout
        self.max_frame_size = max_frame_size
        self.max_frame_seconds = max_frame_seconds
        self.frame_hook = frame_hook
        self.sock: socket.socket | None = None
        self.state = StateMachine(Role.CLIENT)
        self._negotiated_version: int | None = None
        self._next_request_id = secrets.randbits(63) or 1

    @property
    def negotiated_version(self) -> int | None:
        """Protocol version chosen during handshake, or ``None`` before connect."""
        return self._negotiated_version

    def connect(self) -> None:
        if self.state.state is ConnectionState.CLOSED:
            raise ConnectionClosed("client is closed; create a new instance")
        if self.sock is not None:
            raise ConnectionClosed("client is already connected")
        LOGGER.info("connecting to %s:%s", self.host, self.port)
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError:
            LOGGER.exception("connection failed")
            raise
        # Disable Nagle for low-latency request/response exchanges.
        with suppress(OSError):
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(self.timeout)
        try:
            self._handshake()
        except Exception:
            self._close_socket()
            self.state.close()
            raise
        LOGGER.info(
            "handshake complete; negotiated protocol version %s",
            self._negotiated_version,
        )

    def _socket(self) -> socket.socket:
        if self.sock is None:
            raise ConnectionClosed("client is not connected")
        return self.sock

    def _invalidate(self) -> None:
        """Drop the socket and mark this single-use client closed."""
        self._close_socket()
        self.state.close()

    def _raise_protocol(self, code: ErrorCode, reason: str) -> NoReturn:
        exc = ProtocolError(code, reason)
        if exc.code not in APPLICATION_ERROR_CODES:
            self._invalidate()
        raise exc

    def _send(self, message: Message, request_id: int) -> None:
        message_type, body = encode_message(message)
        self.state.on_send(message_type)
        version = self._negotiated_version if self._negotiated_version is not None else PROTOCOL_VERSION
        raw = encode_frame(
            self.key,
            message_type,
            request_id,
            body,
            version=version,
            max_frame_size=self.max_frame_size,
        )
        LOGGER.debug("send %s request_id=%s", message_type.name, request_id)
        try:
            write_frame(self._socket(), raw, hook=self.frame_hook)
        except (ConnectionClosed, TransportTimeout):
            self._invalidate()
            raise

    def _receive(self) -> tuple[int, Message]:
        try:
            frame = read_frame(
                self._socket(),
                self.key,
                max_frame_size=self.max_frame_size,
                header_timeout=self.timeout,
                body_timeout=self.timeout,
                idle_timeout=self.timeout,
                max_frame_seconds=self.max_frame_seconds,
                hook=self.frame_hook,
            )
        except (ConnectionClosed, TransportTimeout):
            self._invalidate()
            raise
        self.state.on_receive(frame.message_type)
        message = decode_message(frame.message_type, frame.body)
        LOGGER.debug("receive %s request_id=%s", frame.message_type.name, frame.request_id)
        if isinstance(message, ErrorMessage):
            exc = ProtocolError(message.code, message.reason)
            if exc.code not in APPLICATION_ERROR_CODES:
                self._invalidate()
            raise exc
        return frame.request_id, message

    def _handshake(self) -> None:
        self._send(Hello(SUPPORTED_VERSIONS), CONTROL_REQUEST_ID)
        request_id, message = self._receive()
        if request_id != CONTROL_REQUEST_ID or not isinstance(message, HelloAck):
            self._raise_protocol(ErrorCode.BAD_STATE, "expected HELLO_ACK control frame")
        if message.selected_version not in SUPPORTED_VERSIONS:
            self._raise_protocol(
                ErrorCode.UNSUPPORTED_VERSION,
                f"server selected unsupported version {message.selected_version}",
            )
        self._negotiated_version = message.selected_version

    def _new_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id = (request_id + 1) & 0xFFFFFFFFFFFFFFFF
        if self._next_request_id == CONTROL_REQUEST_ID:
            self._next_request_id = 1
        return request_id

    def ping(self, nonce: int | None = None) -> int:
        value = secrets.randbits(64) if nonce is None else nonce
        self._send(Ping(value), CONTROL_REQUEST_ID)
        request_id, message = self._receive()
        if request_id != CONTROL_REQUEST_ID or not isinstance(message, Pong):
            self._raise_protocol(ErrorCode.BAD_STATE, "expected PONG control frame")
        if message.nonce != value:
            self._raise_protocol(ErrorCode.MALFORMED_BODY, "PONG nonce did not match PING")
        return message.nonce

    def request(self, command: Command, *arguments: str) -> Response:
        request_id = self._new_request_id()
        self._send(Request(command, tuple(arguments)), request_id)
        response_id, message = self._receive()
        if response_id != request_id:
            self._raise_protocol(
                ErrorCode.MALFORMED_BODY,
                f"response request_id {response_id} does not match {request_id}",
            )
        if not isinstance(message, Response):
            self._raise_protocol(
                ErrorCode.BAD_STATE,
                f"expected RESPONSE, got {type(message).__name__}",
            )
        if message.command is not command:
            self._raise_protocol(ErrorCode.MALFORMED_BODY, "response command does not match request")
        return message

    def close(self, reason: str = "client exit") -> None:
        sock = self.sock
        if sock is None:
            self.state.close()
            return
        try:
            if self.state.state is ConnectionState.READY:
                # Best-effort graceful BYE: if the peer has already gone away,
                # either the send or the acknowledgement read can fail. Teardown
                # must not raise, so both are wrapped and swallowed here.
                try:
                    self._send(Bye(reason), CONTROL_REQUEST_ID)
                    _, response = self._receive()
                    if not isinstance(response, Bye):
                        LOGGER.warning("expected BYE acknowledgement")
                except (ConnectionClosed, ProtocolError):
                    pass
        finally:
            self._close_socket()
            self.state.close()
            LOGGER.info("connection closed")

    def _close_socket(self) -> None:
        sock = self.sock
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        self.sock = None

    def __enter__(self) -> ToyProtoClient:
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
