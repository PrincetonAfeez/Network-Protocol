"""Tiny in-memory application carried by ToyProto REQUEST messages."""
 
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from .constants import MAX_KV_KEYS, Command, ErrorCode
from .errors import ProtocolError
from .types import Request, Response


class ToyApplication:
    def __init__(self, max_keys: int = MAX_KV_KEYS) -> None:
        self._store: dict[str, str] = {}
        self._lock = Lock()
        self._max_keys = max_keys

    def execute(self, request: Request) -> Response:
        command = request.command
        args = request.arguments

        if command is Command.ECHO:
            return Response(command, (args[0],))
        if command is Command.TIME:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return Response(command, (now,))
        if command is Command.KV_PUT:
            key, value = args
            with self._lock:
                if key not in self._store and len(self._store) >= self._max_keys:
                    raise ProtocolError(
                        ErrorCode.STORE_FULL,
                        f"key-value store is full ({self._max_keys} keys)",
                        fatal=False,
                    )
                self._store[key] = value
            return Response(command, ("stored",))
        if command is Command.KV_GET:
            key = args[0]
            with self._lock:
                stored_value = self._store.get(key)
            if stored_value is None:
                raise ProtocolError(
                    ErrorCode.NOT_FOUND,
                    f"key not found: {key}",
                    fatal=False,
                )
            return Response(command, (stored_value,))
        if command is Command.KV_DELETE:
            key = args[0]
            with self._lock:
                existed = self._store.pop(key, None) is not None
            return Response(command, ("deleted" if existed else "not found",))
        # Forward-defensive: decode_message validates the command enum and all
        # five commands are handled above, so this is unreachable in practice.
        raise ProtocolError(  # pragma: no cover
            ErrorCode.UNKNOWN_COMMAND, f"unsupported command: {command}", fatal=False
        )
