"""Formal client/server connection state enforcement."""
 
from __future__ import annotations

from enum import Enum, auto

from .constants import ErrorCode, MessageType
from .errors import ProtocolError


class Role(Enum):
    CLIENT = auto()
    SERVER = auto()


class ConnectionState(Enum):
    NEW = auto()
    HANDSHAKING = auto()
    READY = auto()
    CLOSING = auto()
    CLOSED = auto()


class StateMachine:
    def __init__(self, role: Role) -> None:
        self.role = role
        self.state = ConnectionState.NEW

    def _bad_state(self, direction: str, message_type: MessageType) -> ProtocolError:
        return ProtocolError(
            ErrorCode.BAD_STATE,
            f"{self.role.name.lower()} cannot {direction} {message_type.name} "
            f"while {self.state.name}",
            fatal=False,
        )

    def on_send(self, message_type: MessageType) -> None:
        if self.state is ConnectionState.CLOSED:
            raise self._bad_state("send", message_type)

        if self.role is Role.CLIENT:
            if self.state is ConnectionState.NEW and message_type is MessageType.HELLO:
                self.state = ConnectionState.HANDSHAKING
                return
            if self.state is ConnectionState.READY and message_type in {
                MessageType.PING,
                MessageType.REQUEST,
            }:
                return
            if self.state in {ConnectionState.READY, ConnectionState.CLOSING} and message_type is MessageType.BYE:
                self.state = ConnectionState.CLOSING
                return
        else:
            if self.state is ConnectionState.HANDSHAKING and message_type is MessageType.HELLO_ACK:
                self.state = ConnectionState.READY
                return
            if self.state in {
                ConnectionState.NEW,
                ConnectionState.HANDSHAKING,
                ConnectionState.READY,
            } and message_type is MessageType.ERROR:
                return
            if self.state is ConnectionState.READY and message_type in {
                MessageType.PONG,
                MessageType.RESPONSE,
            }:
                return
            if self.state in {ConnectionState.READY, ConnectionState.CLOSING} and message_type is MessageType.BYE:
                self.state = ConnectionState.CLOSING
                return
        raise self._bad_state("send", message_type)

    def on_receive(self, message_type: MessageType) -> None:
        if self.state is ConnectionState.CLOSED:
            raise self._bad_state("receive", message_type)

        if self.role is Role.SERVER:
            if self.state is ConnectionState.NEW and message_type is MessageType.HELLO:
                self.state = ConnectionState.HANDSHAKING
                return
            if self.state is ConnectionState.READY and message_type in {
                MessageType.PING,
                MessageType.REQUEST,
            }:
                return
            if self.state in {ConnectionState.READY, ConnectionState.CLOSING} and message_type is MessageType.BYE:
                self.state = ConnectionState.CLOSING
                return
        else:
            if self.state is ConnectionState.HANDSHAKING and message_type is MessageType.HELLO_ACK:
                self.state = ConnectionState.READY
                return
            if self.state in {ConnectionState.HANDSHAKING, ConnectionState.READY} and message_type is MessageType.ERROR:
                return
            if self.state is ConnectionState.READY and message_type in {
                MessageType.PONG,
                MessageType.RESPONSE,
            }:
                return
            if self.state in {ConnectionState.READY, ConnectionState.CLOSING} and message_type is MessageType.BYE:
                self.state = ConnectionState.CLOSING
                return
        raise self._bad_state("receive", message_type)

    def close(self) -> None:
        self.state = ConnectionState.CLOSED

