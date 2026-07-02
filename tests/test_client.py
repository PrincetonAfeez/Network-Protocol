"""Client: ToyProto client with state machine and connection handling."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock

import pytest

from toyproto.client import ToyProtoClient
from toyproto.codec import encode_message
from toyproto.constants import CONTROL_REQUEST_ID, Command, ErrorCode
from toyproto.errors import ConnectionClosed, ProtocolError
from toyproto.framing import encode_frame
from toyproto.state_machine import ConnectionState
from toyproto.types import ErrorMessage, HelloAck, Pong, Response

from server_helpers import KEY, one_shot_server, start_server, stop_server


def test_client_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="empty"):
        ToyProtoClient("127.0.0.1", 9000, b"")


def test_client_socket_raises_when_not_connected() -> None:
    client = ToyProtoClient("127.0.0.1", 9000, KEY)
    with pytest.raises(ConnectionClosed, match="not connected"):
        client._socket()


def test_client_close_without_connect_marks_closed() -> None:
    client = ToyProtoClient("127.0.0.1", 9000, KEY)
    client.close()
    assert client.state.state is ConnectionState.CLOSED
    assert client.sock is None


def test_client_close_swallows_peer_loss_during_bye() -> None:
    def drop_after_bye(conn: socket.socket) -> None:
        from toyproto.transport import read_frame

        read_frame(conn, KEY)
        message_type, body = encode_message(HelloAck(1))
        conn.sendall(encode_frame(KEY, message_type, 0, body))
        read_frame(conn, KEY)  # BYE from client
        conn.close()

    port, thread = one_shot_server(drop_after_bye)
    client = ToyProtoClient("127.0.0.1", port, KEY)
    client.connect()
    client.close("bye")
    assert client.state.state is ConnectionState.CLOSED
    thread.join(3)


def test_client_close_warns_on_non_bye_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
    client.connect()
    monkeypatch.setattr(client, "_receive", lambda: (0, Pong(1)))
    with caplog.at_level("WARNING", logger="toyproto.client"):
        client.close()
    assert any("expected BYE acknowledgement" in record.message for record in caplog.records)
    stop_server(server, thread)


def test_client_handshake_rejects_wrong_control_reply() -> None:
    def send_ping_not_ack(conn: socket.socket) -> None:
        from toyproto.transport import read_frame

        read_frame(conn, KEY)
        message_type, body = encode_message(Pong(1))
        conn.sendall(encode_frame(KEY, message_type, 0, body))

    port, thread = one_shot_server(send_ping_not_ack)
    client = ToyProtoClient("127.0.0.1", port, KEY)
    with pytest.raises(ProtocolError, match="HANDSHAKING"):
        client.connect()
    assert client.state.state is ConnectionState.CLOSED
    thread.join(3)


def test_client_handshake_receives_error_from_server() -> None:
    def send_error(conn: socket.socket) -> None:
        from toyproto.transport import read_frame

        read_frame(conn, KEY)
        message_type, body = encode_message(
            ErrorMessage(ErrorCode.UNSUPPORTED_VERSION, "no overlap")
        )
        conn.sendall(encode_frame(KEY, message_type, 0, body))

    port, thread = one_shot_server(send_error)
    client = ToyProtoClient("127.0.0.1", port, KEY)
    with pytest.raises(ProtocolError, match="UNSUPPORTED_VERSION"):
        client.connect()
    assert client.state.state is ConnectionState.CLOSED
    thread.join(3)


def test_client_rejects_response_command_mismatch() -> None:
    def wrong_command(conn: socket.socket) -> None:
        from toyproto.transport import read_frame

        read_frame(conn, KEY)
        message_type, body = encode_message(HelloAck(1))
        conn.sendall(encode_frame(KEY, message_type, 0, body))
        request = read_frame(conn, KEY)
        message_type, body = encode_message(Response(Command.TIME, ("2026-01-01T00:00:00Z",)))
        conn.sendall(encode_frame(KEY, message_type, request.request_id, body))

    port, thread = one_shot_server(wrong_command)
    client = ToyProtoClient("127.0.0.1", port, KEY)
    client.connect()
    with pytest.raises(ProtocolError, match="command does not match"):
        client.request(Command.ECHO, "hi")
    assert client.state.state is ConnectionState.CLOSED
    thread.join(3)


def test_client_rejects_unexpected_response_type(monkeypatch: pytest.MonkeyPatch) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
    client.connect()
    request_id = 4242
    monkeypatch.setattr(client, "_new_request_id", lambda: request_id)
    monkeypatch.setattr(client, "_receive", lambda: (request_id, Pong(9)))
    with pytest.raises(ProtocolError, match="RESPONSE"):
        client.request(Command.ECHO, "hi")
    assert client.state.state.name == "CLOSED"
    stop_server(server, thread)


def test_client_send_invalidates_on_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
    client.connect()

    def fail_write(*args: object, **kwargs: object) -> None:
        raise ConnectionClosed("write failed")

    monkeypatch.setattr("toyproto.client.write_frame", fail_write)
    with pytest.raises(ConnectionClosed):
        client.ping(1)
    assert client.state.state.name == "CLOSED"
    stop_server(server, thread)


def test_client_handshake_rejects_nonzero_ack_request_id() -> None:
    def bad_request_id(conn: socket.socket) -> None:
        from toyproto.transport import read_frame

        read_frame(conn, KEY)
        message_type, body = encode_message(HelloAck(1))
        conn.sendall(encode_frame(KEY, message_type, 7, body))

    port, thread = one_shot_server(bad_request_id)
    client = ToyProtoClient("127.0.0.1", port, KEY)
    with pytest.raises(ProtocolError, match="HELLO_ACK"):
        client.connect()
    assert client.state.state.name == "CLOSED"
    thread.join(3)


def test_client_send_invalidates_on_connection_closed() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
    client.connect()
    stop_server(server, thread)
    with pytest.raises(ConnectionClosed):
        client.request(Command.ECHO, "late")
    assert client.state.state is ConnectionState.CLOSED


def test_client_new_request_id_skips_control_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ToyProtoClient("127.0.0.1", 9000, KEY)
    monkeypatch.setattr(client, "_next_request_id", CONTROL_REQUEST_ID)
    assert client._new_request_id() == CONTROL_REQUEST_ID
    assert client._next_request_id == 1


def test_client_frame_hook_is_invoked() -> None:
    seen: list[tuple[str, int]] = []

    def hook(direction: str, data: bytes) -> None:
        seen.append((direction, len(data)))

    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY, frame_hook=hook) as client:
            client.ping(3)
    finally:
        stop_server(server, thread)
    assert ("OUT", 60) in seen or any(d == "OUT" for d, _ in seen)
    assert any(d == "IN" for d, _ in seen)


def test_client_context_manager_connects_and_closes() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.state.state is ConnectionState.READY
            assert client.ping(2) == 2
        assert client.state.state is ConnectionState.CLOSED
    finally:
        stop_server(server, thread)


def test_client_close_socket_tolerates_shutdown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ToyProtoClient("127.0.0.1", 9000, KEY)
    mock_sock = MagicMock()
    mock_sock.shutdown.side_effect = OSError("already closed")
    client.sock = mock_sock
    client._close_socket()
    mock_sock.close.assert_called_once()
    assert client.sock is None
