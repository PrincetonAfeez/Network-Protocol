"""Protocol-specific failures with stable wire error codes."""

from __future__ import annotations

from .constants import ErrorCode, FATAL_ERROR_CODES


class ToyProtoError(Exception):
    """Base class for expected ToyProto failures."""


class ProtocolError(ToyProtoError):
    def __init__(
        self,
        code: ErrorCode,
        reason: str,
        *,
        fatal: bool | None = None,
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.fatal = code in FATAL_ERROR_CODES if fatal is None else fatal

    def __str__(self) -> str:
        return f"{self.code.name}: {self.reason}"


class ConnectionClosed(ToyProtoError):
    """The peer closed the byte stream."""


class TransportTimeout(ProtocolError):
    def __init__(self, reason: str = "network read timed out") -> None:
        super().__init__(ErrorCode.TIMEOUT, reason, fatal=True)

