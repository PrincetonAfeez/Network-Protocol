"""Pure binary serializer: typed messages <-> deterministic body bytes."""

from __future__ import annotations

import struct

from .constants import Command, ErrorCode, MessageType
from .errors import ProtocolError
from .types import (
    MESSAGE_TYPES,
    Bye,
    ErrorMessage,
    Hello,
    HelloAck,
    Message,
    Ping,
    Pong,
    Request,
    Response,
)

_REQUEST_ARITY = {
    Command.ECHO: 1,
    Command.TIME: 0,
    Command.KV_PUT: 2,
    Command.KV_GET: 1,
    Command.KV_DELETE: 1,
}
_RESPONSE_ARITY = {command: 1 for command in Command}


def _malformed(reason: str) -> ProtocolError:
    return ProtocolError(ErrorCode.MALFORMED_BODY, reason, fatal=False)


class _Writer:
    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def u8(self, value: int) -> None:
        if not 0 <= value <= 0xFF:
            raise _malformed(f"uint8 out of range: {value}")
        self.parts.append(struct.pack("!B", value))

    def u16(self, value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise _malformed(f"uint16 out of range: {value}")
        self.parts.append(struct.pack("!H", value))

    def u64(self, value: int) -> None:
        if not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
            raise _malformed(f"uint64 out of range: {value}")
        self.parts.append(struct.pack("!Q", value))

    def string(self, value: str) -> None:
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _malformed("string cannot be encoded as UTF-8") from exc
        if len(encoded) > 0xFFFF:
            raise _malformed("UTF-8 string exceeds 65535 bytes")
        self.u16(len(encoded))
        self.parts.append(encoded)

    def finish(self) -> bytes:
        return b"".join(self.parts)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise _malformed(
                f"field needs {size} bytes at offset {self.offset}, "
                f"only {len(self.data) - self.offset} remain"
            )
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return int.from_bytes(self._take(1), "big")

    def u16(self) -> int:
        return int.from_bytes(self._take(2), "big")

    def u64(self) -> int:
        return int.from_bytes(self._take(8), "big")

    def string(self) -> str:
        length = self.u16()
        raw = self._take(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _malformed("string contains invalid UTF-8") from exc

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise _malformed(f"{len(self.data) - self.offset} unexpected trailing bytes")


def message_type_for(message: Message) -> MessageType:
    try:
        return MESSAGE_TYPES[type(message)]
    except KeyError as exc:
        raise TypeError(f"unsupported message class: {type(message).__name__}") from exc


def _enum_value(enum_type: type[Command] | type[ErrorCode], raw: int, label: str) -> Command | ErrorCode:
    try:
        return enum_type(raw)
    except ValueError as exc:
        code = ErrorCode.UNKNOWN_COMMAND if enum_type is Command else ErrorCode.MALFORMED_BODY
        raise ProtocolError(code, f"unknown {label} value: 0x{raw:02x}", fatal=False) from exc


def encode_message(message: Message) -> tuple[MessageType, bytes]:
    writer = _Writer()
    message_type = message_type_for(message)

    if isinstance(message, Hello):
        versions = message.supported_versions
        if not versions or len(versions) > 0xFF or len(set(versions)) != len(versions):
            raise _malformed("HELLO versions must be 1..255 unique uint8 values")
        writer.u8(len(versions))
        for version in versions:
            writer.u8(version)
    elif isinstance(message, HelloAck):
        writer.u8(message.selected_version)
    elif isinstance(message, (Ping, Pong)):
        writer.u64(message.nonce)
    elif isinstance(message, Request):
        expected = _REQUEST_ARITY[message.command]
        if len(message.arguments) != expected:
            raise _malformed(
                f"{message.command.name} expects {expected} arguments, got {len(message.arguments)}"
            )
        writer.u8(int(message.command))
        writer.u8(len(message.arguments))
        for argument in message.arguments:
            writer.string(argument)
    elif isinstance(message, Response):
        expected = _RESPONSE_ARITY[message.command]
        if len(message.values) != expected:
            raise _malformed(
                f"{message.command.name} response expects {expected} value, got {len(message.values)}"
            )
        writer.u8(int(message.command))
        writer.u8(len(message.values))
        for value in message.values:
            writer.string(value)
    elif isinstance(message, ErrorMessage):
        writer.u16(int(message.code))
        writer.string(message.reason)
    elif isinstance(message, Bye):
        writer.string(message.reason)
    else:
        raise TypeError(f"unsupported message class: {type(message).__name__}")

    return message_type, writer.finish()


def decode_message(message_type: MessageType, body: bytes) -> Message:
    reader = _Reader(body)

    if message_type is MessageType.HELLO:
        count = reader.u8()
        if count == 0:
            raise _malformed("HELLO must advertise at least one version")
        versions = tuple(reader.u8() for _ in range(count))
        if len(set(versions)) != len(versions):
            raise _malformed("HELLO contains duplicate versions")
        result: Message = Hello(versions)
    elif message_type is MessageType.HELLO_ACK:
        result = HelloAck(reader.u8())
    elif message_type is MessageType.PING:
        result = Ping(reader.u64())
    elif message_type is MessageType.PONG:
        result = Pong(reader.u64())
    elif message_type in (MessageType.REQUEST, MessageType.RESPONSE):
        command = _enum_value(Command, reader.u8(), "command")
        assert isinstance(command, Command)
        arity = _REQUEST_ARITY if message_type is MessageType.REQUEST else _RESPONSE_ARITY
        expected = arity[command]
        count = reader.u8()
        # Validate the declared field count against the command's known arity
        # before consuming any fields, so a bogus count is rejected up front.
        if count != expected:
            raise _malformed(f"{command.name} expects {expected} fields, got {count}")
        values = tuple(reader.string() for _ in range(count))
        result = Request(command, values) if message_type is MessageType.REQUEST else Response(command, values)
    elif message_type is MessageType.ERROR:
        error_code = _enum_value(ErrorCode, reader.u16(), "error code")
        assert isinstance(error_code, ErrorCode)
        result = ErrorMessage(error_code, reader.string())
    elif message_type is MessageType.BYE:
        result = Bye(reader.string())
    else:  # pragma: no cover - forward-defensive: every MessageType has an arm above
        raise ProtocolError(
            ErrorCode.UNKNOWN_MESSAGE_TYPE,
            f"unknown message type: {int(message_type)}",
            fatal=True,
        )

    reader.finish()
    return result
