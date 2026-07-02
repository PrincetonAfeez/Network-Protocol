"""Thread-per-connection ToyProto server with a shared in-memory store."""

from __future__ import annotations

import socket
import threading
from unittest.mock import MagicMock

import pytest

from toyproto.codec import encode_message
from toyproto.constants import CONTROL_REQUEST_ID, Command, ErrorCode, MessageType
from toyproto.errors import ConnectionClosed, ProtocolError
from toyproto.framing import encode_frame
from toyproto.server import ToyProtoServer, _Session
from toyproto.state_machine import Role, StateMachine
from toyproto.transport import read_frame
from toyproto.types import Bye, Hello, Ping, Request

from server_helpers import KEY, start_server, stop_server


def test_server_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="empty"):
        ToyProtoServer("127.0.0.1", 0, b"")


def test_server_rejects_invalid_capacity_limits() -> None:
    with pytest.raises(ValueError, match="max_kv_keys"):
        ToyProtoServer("127.0.0.1", 0, KEY, max_kv_keys=0)
    with pytest.raises(ValueError, match="max_malformed_frames"):
        ToyProtoServer("127.0.0.1", 0, KEY, max_malformed_frames=0)
    with pytest.raises(ValueError, match="max_connections"):
        ToyProtoServer("127.0.0.1", 0, KEY, max_connections=0)


def test_server_rejects_non_positive_read_timeouts() -> None:
    with pytest.raises(ValueError, match="header_timeout"):
        ToyProtoServer("127.0.0.1", 0, KEY, header_timeout=0)
    with pytest.raises(ValueError, match="body_timeout"):
        ToyProtoServer("127.0.0.1", 0, KEY, body_timeout=0)


def test_server_deprecated_timeout_alias_sets_idle_timeout() -> None:
    server = ToyProtoServer("127.0.0.1", 0, KEY, timeout=42.0)
    assert server.idle_timeout == 42.0


def test_server_hello_with_nonzero_request_id_closes_with_error() -> None:
    server, thread = start_server(max_malformed_frames=1)
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello((1,)))
            sock.sendall(encode_frame(KEY, message_type, 99, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
            with pytest.raises(ConnectionClosed):
                read_frame(sock, KEY)
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_server_ping_with_nonzero_request_id_closes_with_error() -> None:
    server, thread = start_server(max_malformed_frames=1)
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello((1,)))
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            read_frame(sock, KEY)
            message_type, body = encode_message(Ping(1))
            sock.sendall(encode_frame(KEY, message_type, 7, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_server_request_with_control_request_id_closes_with_error() -> None:
    server, thread = start_server(max_malformed_frames=1)
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello((1,)))
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            read_frame(sock, KEY)
            message_type, body = encode_message(Request(Command.ECHO, ("hi",)))
            sock.sendall(encode_frame(KEY, message_type, CONTROL_REQUEST_ID, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_server_bye_with_nonzero_request_id_closes_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server, thread = start_server(max_malformed_frames=1)
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        sock.settimeout(2.0)
        try:
            message_type, body = encode_message(Hello((1,)))
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            read_frame(sock, KEY)
            message_type, body = encode_message(Bye("later"))
            sock.sendall(encode_frame(KEY, message_type, 5, body))
            with caplog.at_level("WARNING", logger="toyproto.server"):
                with pytest.raises(ConnectionClosed):
                    read_frame(sock, KEY)
            assert any("BYE request_id must be 0" in record.message for record in caplog.records)
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_server_accept_loop_continues_after_listener_timeout() -> None:
    server = ToyProtoServer("127.0.0.1", 0, KEY)
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    threading.Event().wait(0.6)
    server.shutdown()
    thread.join(5)
    assert not thread.is_alive()


def test_server_guarded_handler_logs_unexpected_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = ToyProtoServer("127.0.0.1", 0, KEY)
    server._slots.acquire()

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    server._handle_connection = boom  # type: ignore[method-assign]
    connection = MagicMock()
    with caplog.at_level("ERROR", logger="toyproto.server"):
        server._handle_connection_guarded(connection, ("127.0.0.1", 1234))
    assert any("unexpected connection handler failure" in record.message for record in caplog.records)


def test_server_send_error_swallows_write_failures() -> None:
    server = ToyProtoServer("127.0.0.1", 0, KEY)
    state = StateMachine(Role.SERVER)
    session = _Session()
    conn = MagicMock()
    conn.sendall.side_effect = OSError("gone")
    server._send_error(
        conn,
        state,
        1,
        ProtocolError(ErrorCode.BAD_STATE, "bad", fatal=False),
        session,
    )
