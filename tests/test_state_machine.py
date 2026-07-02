"""StateMachine: formal client/server connection state enforcement."""

from __future__ import annotations

import pytest

from toyproto.constants import MessageType
from toyproto.errors import ProtocolError
from toyproto.state_machine import ConnectionState, Role, StateMachine


def test_server_rejects_request_before_hello() -> None:
    state = StateMachine(Role.SERVER)
    with pytest.raises(ProtocolError, match="BAD_STATE"):
        state.on_receive(MessageType.REQUEST)


def test_client_rejects_response_before_hello_ack() -> None:
    state = StateMachine(Role.CLIENT)
    state.on_send(MessageType.HELLO)
    with pytest.raises(ProtocolError, match="BAD_STATE"):
        state.on_receive(MessageType.RESPONSE)


def test_handshake_ready_and_bye_flow() -> None:
    client = StateMachine(Role.CLIENT)
    client.on_send(MessageType.HELLO)
    assert client.state is ConnectionState.HANDSHAKING
    client.on_receive(MessageType.HELLO_ACK)
    assert client.state is ConnectionState.READY
    client.on_send(MessageType.BYE)
    assert client.state is ConnectionState.CLOSING
    client.on_receive(MessageType.BYE)
    client.close()
    assert client.state is ConnectionState.CLOSED


def test_server_handshake_transitions() -> None:
    server = StateMachine(Role.SERVER)
    assert server.state is ConnectionState.NEW
    server.on_receive(MessageType.HELLO)
    assert server.state is ConnectionState.HANDSHAKING
    server.on_send(MessageType.HELLO_ACK)
    assert server.state is ConnectionState.READY


def test_server_rejects_ping_before_handshake() -> None:
    state = StateMachine(Role.SERVER)
    with pytest.raises(ProtocolError, match="BAD_STATE"):
        state.on_receive(MessageType.PING)


def test_server_ready_accepts_request_and_bye() -> None:
    state = StateMachine(Role.SERVER)
    state.on_receive(MessageType.HELLO)
    state.on_send(MessageType.HELLO_ACK)
    state.on_receive(MessageType.REQUEST)
    state.on_receive(MessageType.BYE)
    assert state.state is ConnectionState.CLOSING


def test_server_sends_pong_and_response_in_ready() -> None:
    state = StateMachine(Role.SERVER)
    state.on_receive(MessageType.HELLO)
    state.on_send(MessageType.HELLO_ACK)
    state.on_send(MessageType.PONG)
    state.on_send(MessageType.RESPONSE)


def test_client_handshaking_accepts_error() -> None:
    state = StateMachine(Role.CLIENT)
    state.on_send(MessageType.HELLO)
    state.on_receive(MessageType.ERROR)


def test_closed_endpoint_rejects_all_traffic() -> None:
    state = StateMachine(Role.CLIENT)
    state.close()
    with pytest.raises(ProtocolError, match="BAD_STATE"):
        state.on_send(MessageType.HELLO)
    with pytest.raises(ProtocolError, match="BAD_STATE"):
        state.on_receive(MessageType.PONG)


def test_server_rejects_invalid_send_in_handshaking() -> None:
    state = StateMachine(Role.SERVER)
    state.on_receive(MessageType.HELLO)
    with pytest.raises(ProtocolError, match="cannot send PING"):
        state.on_send(MessageType.PING)


def test_client_rejects_invalid_send_in_new() -> None:
    state = StateMachine(Role.CLIENT)
    with pytest.raises(ProtocolError, match="cannot send PING"):
        state.on_send(MessageType.PING)


def test_server_can_send_error_in_handshaking() -> None:
    state = StateMachine(Role.SERVER)
    state.on_receive(MessageType.HELLO)
    state.on_send(MessageType.ERROR)


def test_client_ready_accepts_request_send() -> None:
    state = StateMachine(Role.CLIENT)
    state.on_send(MessageType.HELLO)
    state.on_receive(MessageType.HELLO_ACK)
    state.on_send(MessageType.REQUEST)
