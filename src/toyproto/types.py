"""Typed frames and message values."""
 
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .constants import Command, ErrorCode, MessageType


@dataclass(frozen=True, slots=True)
class Frame:
    version: int
    message_type: MessageType
    flags: int
    request_id: int
    body: bytes
    hmac_tag: bytes


@dataclass(frozen=True, slots=True)
class Hello:
    supported_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class HelloAck:
    selected_version: int


@dataclass(frozen=True, slots=True)
class Ping:
    nonce: int


@dataclass(frozen=True, slots=True)
class Pong:
    nonce: int


@dataclass(frozen=True, slots=True)
class Request:
    command: Command
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Response:
    command: Command
    values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ErrorMessage:
    code: ErrorCode
    reason: str


@dataclass(frozen=True, slots=True)
class Bye:
    reason: str = ""


Message: TypeAlias = Hello | HelloAck | Ping | Pong | Request | Response | ErrorMessage | Bye


MESSAGE_TYPES: dict[type[object], MessageType] = {
    Hello: MessageType.HELLO,
    HelloAck: MessageType.HELLO_ACK,
    Ping: MessageType.PING,
    Pong: MessageType.PONG,
    Request: MessageType.REQUEST,
    Response: MessageType.RESPONSE,
    ErrorMessage: MessageType.ERROR,
    Bye: MessageType.BYE,
}

