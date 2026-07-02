"""App: ToyProto application layer with in-memory store."""

from __future__ import annotations

import pytest

from toyproto.app import ToyApplication
from toyproto.constants import Command, ErrorCode
from toyproto.errors import ProtocolError
from toyproto.types import Request


def test_app_echo_and_time() -> None:
    app = ToyApplication()
    assert app.execute(Request(Command.ECHO, ("hello",))).values == ("hello",)
    timestamp = app.execute(Request(Command.TIME)).values[0]
    assert timestamp.endswith("Z")


def test_kv_roundtrip_put_get_delete() -> None:
    app = ToyApplication()
    assert app.execute(Request(Command.KV_PUT, ("k", "v"))).values == ("stored",)
    assert app.execute(Request(Command.KV_GET, ("k",))).values == ("v",)
    assert app.execute(Request(Command.KV_DELETE, ("k",))).values == ("deleted",)
    assert app.execute(Request(Command.KV_DELETE, ("k",))).values == ("not found",)


def test_kv_get_missing_key_raises_not_found() -> None:
    app = ToyApplication()
    with pytest.raises(ProtocolError) as exc:
        app.execute(Request(Command.KV_GET, ("absent",)))
    assert exc.value.code is ErrorCode.NOT_FOUND


def test_kv_store_cap_rejects_new_keys_when_full() -> None:
    app = ToyApplication(max_keys=2)
    assert app.execute(Request(Command.KV_PUT, ("a", "1"))).values == ("stored",)
    assert app.execute(Request(Command.KV_PUT, ("b", "2"))).values == ("stored",)
    with pytest.raises(ProtocolError) as exc:
        app.execute(Request(Command.KV_PUT, ("c", "3")))
    assert exc.value.code is ErrorCode.STORE_FULL
    # Overwriting an existing key is still allowed at capacity.
    assert app.execute(Request(Command.KV_PUT, ("a", "updated"))).values == ("stored",)
    assert app.execute(Request(Command.KV_GET, ("a",))).values == ("updated",)
