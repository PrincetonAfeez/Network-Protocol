from __future__ import annotations

import socket
import threading
import time

import pytest

from toyproto.client import ToyProtoClient
from toyproto.codec import decode_message, encode_message
from toyproto.constants import HEADER_SIZE, SUPPORTED_VERSIONS, Command, MessageType
from toyproto.errors import ConnectionClosed, ProtocolError
from toyproto.framing import encode_frame
from toyproto.server import ToyProtoServer
from toyproto.transport import read_frame
from toyproto.types import ErrorMessage, Hello, Ping, Request

from server_helpers import KEY, start_server, stop_server

def test_end_to_end_handshake_ping_and_application_commands() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.ping(1234) == 1234
            assert client.request(Command.ECHO, "hello").values == ("hello",)
            assert client.request(Command.KV_PUT, "color", "blue").values == ("stored",)
            assert client.request(Command.KV_GET, "color").values == ("blue",)
            assert client.request(Command.KV_DELETE, "color").values == ("deleted",)
            assert client.request(Command.TIME).values[0].endswith("Z")
    finally:
        stop_server(server, thread)


def test_wrong_state_request_receives_error_then_connection_closes() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Request(Command.ECHO, ("too soon",)))
            sock.sendall(encode_frame(KEY, message_type, 1, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
            message = decode_message(frame.message_type, frame.body)
            assert isinstance(message, ErrorMessage)
            assert message.code.name == "BAD_STATE"
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_unsupported_version_handshake_is_rejected_and_closes() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello((2,)))  # advertise only version 2
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
            message = decode_message(frame.message_type, frame.body)
            assert isinstance(message, ErrorMessage)
            assert message.code.name == "UNSUPPORTED_VERSION"
            with pytest.raises(ConnectionClosed):
                read_frame(sock, KEY)
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_kv_get_missing_key_errors_but_keeps_connection_open() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            with pytest.raises(ProtocolError) as exc:
                client.request(Command.KV_GET, "absent")
            assert exc.value.code.name == "NOT_FOUND"
            # An application error must not close the connection.
            assert client.request(Command.ECHO, "still up").values == ("still up",)
    finally:
        stop_server(server, thread)


def test_unknown_command_opcode_is_rejected_and_closes() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello(SUPPORTED_VERSIONS))
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            read_frame(sock, KEY)  # HELLO_ACK
            # REQUEST carrying an unknown command opcode (0xFF) and zero arguments.
            sock.sendall(encode_frame(KEY, MessageType.REQUEST, 7, b"\xff\x00"))
            frame = read_frame(sock, KEY)
            message = decode_message(frame.message_type, frame.body)
            assert isinstance(message, ErrorMessage)
            assert message.code.name == "UNKNOWN_COMMAND"
            with pytest.raises(ConnectionClosed):
                read_frame(sock, KEY)
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_server_refuses_connections_beyond_the_cap() -> None:
    server = ToyProtoServer(
        "127.0.0.1", 0, KEY, max_connections=1, header_timeout=1.0, body_timeout=1.0
    )
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert server.bound_port is not None
    try:
        # The first client occupies the only slot; its handshake confirms the
        # handler (and thus the slot) is active.
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as first:
            assert first.ping(1) == 1
            # A second connection is accepted then immediately closed (at capacity).
            second = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
            try:
                with pytest.raises(ConnectionClosed):
                    read_frame(second, KEY)
            finally:
                second.close()
            # The first connection is unaffected.
            assert first.ping(2) == 2
    finally:
        server.shutdown()
        thread.join(3)
        assert not thread.is_alive()


def test_client_disables_nagle() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.sock is not None
            assert client.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
    finally:
        stop_server(server, thread)


def test_server_enforces_configurable_read_deadline() -> None:
    server = ToyProtoServer(
        "127.0.0.1", 0, KEY, max_frame_seconds=0.3, header_timeout=2.0, body_timeout=2.0
    )
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert server.bound_port is not None
    sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=3)
    try:
        message_type, body = encode_message(Hello(SUPPORTED_VERSIONS))
        sock.sendall(encode_frame(KEY, message_type, 0, body))
        read_frame(sock, KEY)  # HELLO_ACK
        message_type, body = encode_message(Ping(42))
        ping = encode_frame(KEY, message_type, 0, body)
        sock.sendall(ping[:HEADER_SIZE])  # header now; dribble the body below

        def dribble() -> None:
            try:
                for byte in ping[HEADER_SIZE:]:
                    time.sleep(0.2)
                    sock.sendall(bytes([byte]))
            except OSError:
                pass

        threading.Thread(target=dribble, daemon=True).start()
        # The server hits its 0.3s total read deadline (a fatal timeout) and
        # closes, so our read sees EOF rather than a PONG.
        with pytest.raises(ConnectionClosed):
            read_frame(sock, KEY)
    finally:
        sock.close()
        server.shutdown()
        thread.join(3)


def test_shutdown_closes_idle_connection_promptly() -> None:
    # Long idle/read timeouts: a correct shutdown must close the live connection
    # itself rather than waiting for these to expire.
    server = ToyProtoServer(
        "127.0.0.1", 0, KEY, timeout=30.0, header_timeout=30.0, body_timeout=30.0
    )
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert server.bound_port is not None
    sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=3)
    try:
        message_type, body = encode_message(Hello(SUPPORTED_VERSIONS))
        sock.sendall(encode_frame(KEY, message_type, 0, body))
        read_frame(sock, KEY)  # HELLO_ACK; the handler now parks in recv
        threading.Timer(0.2, server.shutdown).start()
        with pytest.raises(ConnectionClosed):
            # Wakes with EOF when shutdown() closes the connection (~0.2s),
            # not after the 30s idle timeout.
            read_frame(sock, KEY)
    finally:
        sock.close()
        server.shutdown()
        thread.join(3)
        assert not thread.is_alive()


def test_graceful_bye_shutdown() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
        client.connect()
        assert client.ping(99) == 99
        client.close("done")
        assert client.state.state.name == "CLOSED"
    finally:
        stop_server(server, thread)


def test_kv_store_full_over_the_wire() -> None:
    server = ToyProtoServer(
        "127.0.0.1", 0, KEY, max_kv_keys=1, header_timeout=1.0, body_timeout=1.0
    )
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.request(Command.KV_PUT, "a", "1").values == ("stored",)
            with pytest.raises(ProtocolError) as exc:
                client.request(Command.KV_PUT, "b", "2")
            assert exc.value.code.name == "STORE_FULL"
            assert client.request(Command.KV_PUT, "a", "updated").values == ("stored",)
    finally:
        server.shutdown()
        thread.join(3)


def test_malformed_frame_budget_allows_one_recovery() -> None:
    server = ToyProtoServer(
        "127.0.0.1",
        0,
        KEY,
        max_malformed_frames=2,
        header_timeout=1.0,
        body_timeout=1.0,
    )
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.ping(1) == 1
            sock = client.sock
            assert sock is not None
            message_type, body = encode_message(Ping(2))
            sock.sendall(encode_frame(KEY, message_type, 1, body))
            frame = read_frame(sock, KEY)
            assert frame.message_type is MessageType.ERROR
            assert client.ping(3) == 3
            sock.sendall(encode_frame(KEY, message_type, 2, body))
            read_frame(sock, KEY)
            with pytest.raises(ConnectionClosed):
                read_frame(sock, KEY)
    finally:
        server.shutdown()
        thread.join(3)


def test_server_internal_error_is_reported_then_closes(monkeypatch) -> None:
    server, thread = start_server()
    assert server.bound_port is not None

    def boom(request: Request) -> object:
        raise RuntimeError("simulated handler failure")

    monkeypatch.setattr(server.application, "execute", boom)
    try:
        sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=2)
        try:
            message_type, body = encode_message(Hello(SUPPORTED_VERSIONS))
            sock.sendall(encode_frame(KEY, message_type, 0, body))
            read_frame(sock, KEY)
            message_type, body = encode_message(Request(Command.ECHO, ("fail",)))
            sock.sendall(encode_frame(KEY, message_type, 9, body))
            frame = read_frame(sock, KEY)
            message = decode_message(frame.message_type, frame.body)
            assert isinstance(message, ErrorMessage)
            assert message.code.name == "INTERNAL_ERROR"
            with pytest.raises(ConnectionClosed):
                read_frame(sock, KEY)
        finally:
            sock.close()
    finally:
        stop_server(server, thread)


def test_client_rejects_second_connect_after_close() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        client = ToyProtoClient("127.0.0.1", server.bound_port, KEY)
        client.connect()
        client.close()
        with pytest.raises(ConnectionClosed, match="client is closed"):
            client.connect()
    finally:
        stop_server(server, thread)


def test_negotiated_version_is_stored_on_client() -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        with ToyProtoClient("127.0.0.1", server.bound_port, KEY) as client:
            assert client.negotiated_version == 1
    finally:
        stop_server(server, thread)

