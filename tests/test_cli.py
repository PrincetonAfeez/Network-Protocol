"""Cli: command-line interface for ToyProto."""

from __future__ import annotations

import argparse
import errno
import json
import threading
from pathlib import Path

import pytest

from toyproto import __version__
from toyproto.cli import _interactive, _key_from_args, build_parser, main
from toyproto.constants import IDLE_TIMEOUT, ErrorCode
from toyproto.errors import ConnectionClosed, ProtocolError
from toyproto.server import ToyProtoServer

from server_helpers import KEY, start_server, stop_server

FIXTURES = Path(__file__).parent / "fixtures" / "frames"
FIXTURE_KEY = "fixture-test-key"


def test_server_idle_timeout_is_separate_from_read_timeout() -> None:
    parser = build_parser()
    default = parser.parse_args(["server"])
    assert default.idle_timeout == IDLE_TIMEOUT
    assert default.timeout == 5.0
    custom = parser.parse_args(["server", "--idle-timeout", "30", "--timeout", "2"])
    assert custom.idle_timeout == 30.0
    assert custom.timeout == 2.0


def test_cli_version_flag_prints_version_and_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_inline_key_is_stripped(monkeypatch) -> None:
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)
    args = argparse.Namespace(key="  secret  ", key_file=None)
    assert _key_from_args(args) == b"secret"


def test_key_file_is_stripped(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)
    key_file = tmp_path / "shared.key"
    key_file.write_bytes(b"secret\n")
    args = argparse.Namespace(key=None, key_file=key_file)
    assert _key_from_args(args) == b"secret"


def test_env_key_is_stripped(monkeypatch) -> None:
    monkeypatch.setenv("TOYPROTO_KEY", "secret\n")
    args = argparse.Namespace(key=None, key_file=None)
    assert _key_from_args(args) == b"secret"


def test_all_key_sources_yield_identical_bytes(tmp_path, monkeypatch) -> None:
    # The footgun this guards against: the same secret supplied three ways used
    # to produce three different key bytes (only the file was stripped), causing
    # silent HMAC mismatches between client and server.
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)
    key_file = tmp_path / "shared.key"
    key_file.write_bytes(b"shared-secret\n")
    from_inline = _key_from_args(argparse.Namespace(key="shared-secret", key_file=None))
    from_file = _key_from_args(argparse.Namespace(key=None, key_file=key_file))
    monkeypatch.setenv("TOYPROTO_KEY", "shared-secret")
    from_env = _key_from_args(argparse.Namespace(key=None, key_file=None))
    assert from_inline == from_file == from_env == b"shared-secret"


def test_cli_inspect_valid_fixture_returns_zero(capsys) -> None:
    rc = main(["inspect", str(FIXTURES / "valid_hello.bin"), "--key", FIXTURE_KEY])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is True
    assert report["hmac_valid"] is True
    assert report["message_type"] == "HELLO"


def test_cli_inspect_bad_fixture_returns_runtime_error(capsys) -> None:
    rc = main(["inspect", str(FIXTURES / "bad_magic.bin"), "--key", FIXTURE_KEY])
    assert rc == 3
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert "error" in report


def test_cli_hexdump_renders_header_fields(capsys) -> None:
    rc = main(["hexdump", str(FIXTURES / "valid_ping.bin")])
    assert rc == 0
    assert "magic:" in capsys.readouterr().out


def test_cli_hexdump_missing_file_returns_runtime_error(capsys) -> None:
    rc = main(["hexdump", str(FIXTURES / "does_not_exist_98765.bin")])
    assert rc == 3
    assert "cannot read" in capsys.readouterr().err


def test_interactive_breaks_on_dropped_connection(monkeypatch, capsys) -> None:
    # Three commands queued: a correct loop must stop after the first failure,
    # not keep prompting against a dead socket (which would exhaust the iter).
    commands = iter(["ping", "ping", "ping"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(commands))

    class DeadClient:
        def ping(self) -> int:
            raise ConnectionClosed("server went away")

    _interactive(DeadClient())  # type: ignore[arg-type]
    assert "connection closed" in capsys.readouterr().err


def test_interactive_exits_cleanly_on_keyboard_interrupt(monkeypatch) -> None:
    def interrupt(prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    _interactive(object())  # type: ignore[arg-type]  # must return, not propagate


def test_cli_hexdump_refuses_oversized_file(tmp_path, capsys) -> None:
    from toyproto.constants import HEADER_SIZE, MAX_FRAME_SIZE

    big = tmp_path / "huge.bin"
    big.write_bytes(b"\x00" * (HEADER_SIZE + MAX_FRAME_SIZE + 1))
    rc = main(["hexdump", str(big)])
    assert rc == 3
    assert "larger than a single frame" in capsys.readouterr().err


def test_cli_keyboard_interrupt_returns_130(monkeypatch) -> None:
    import toyproto.cli as cli_module

    def boom(*args: object, **kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_module, "inspect_file", boom)
    rc = main(["inspect", str(FIXTURES / "valid_hello.bin"), "--key", FIXTURE_KEY])
    assert rc == 130


def test_interactive_banner_mentions_idle_timeout(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "quit")
    _interactive(_NoOpClient())  # type: ignore[arg-type]
    assert "--idle-timeout" in capsys.readouterr().out


class _NoOpClient:
    def ping(self) -> int:
        raise AssertionError("should not be called")


def test_cli_ping_against_running_server(capsys) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        rc = main(
            [
                "ping",
                "--host",
                "127.0.0.1",
                "--port",
                str(server.bound_port),
                "--key",
                KEY.decode(),
            ]
        )
        assert rc == 0
        assert "PONG" in capsys.readouterr().out
    finally:
        stop_server(server, thread)


def test_cli_echo_against_running_server(capsys) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        rc = main(
            [
                "echo",
                "cli-test",
                "--host",
                "127.0.0.1",
                "--port",
                str(server.bound_port),
                "--key",
                KEY.decode(),
            ]
        )
        assert rc == 0
        assert capsys.readouterr().out.strip() == "cli-test"
    finally:
        stop_server(server, thread)


def test_cli_server_starts_and_stops(monkeypatch) -> None:
    import toyproto.cli as cli_module

    started = threading.Event()

    class ImmediateServer:
        def serve_forever(self, *, ready: threading.Event | None = None) -> None:
            if ready:
                ready.set()
            started.set()
            raise KeyboardInterrupt

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(cli_module, "ToyProtoServer", lambda *args, **kwargs: ImmediateServer())
    rc = main(["server", "--key", "demo-key"])
    assert rc == 0
    assert started.is_set()


def test_cli_time_put_get_delete_against_running_server(capsys) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    base = ["--host", "127.0.0.1", "--port", str(server.bound_port), "--key", KEY.decode()]
    try:
        assert main(["put", "shade", "green", *base]) == 0
        assert capsys.readouterr().out.strip() == "stored"
        assert main(["get", "shade", *base]) == 0
        assert capsys.readouterr().out.strip() == "green"
        assert main(["time", *base]) == 0
        assert capsys.readouterr().out.strip().endswith("Z")
        assert main(["delete", "shade", *base]) == 0
        assert capsys.readouterr().out.strip() == "deleted"
    finally:
        stop_server(server, thread)


def test_interactive_exits_after_connection_level_protocol_error(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fake_input(prompt: str = "") -> str:
        calls.append("prompt")
        return "ping"

    class BadStateClient:
        def ping(self) -> int:
            raise ProtocolError(ErrorCode.BAD_STATE, "wrong phase", fatal=False)

    monkeypatch.setattr("builtins.input", fake_input)
    _interactive(BadStateClient())  # type: ignore[arg-type]
    assert len(calls) == 1
    assert "error:" in capsys.readouterr().err


def test_interactive_continues_after_not_found(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fake_input(prompt: str = "") -> str:
        calls.append("prompt")
        return "get missing" if len(calls) == 1 else "quit"

    class MissingKeyClient:
        def request(self, command: object, *args: str) -> object:
            raise ProtocolError(ErrorCode.NOT_FOUND, "key not found", fatal=False)

    monkeypatch.setattr("builtins.input", fake_input)
    _interactive(MissingKeyClient())  # type: ignore[arg-type]
    assert len(calls) == 2


def test_cli_rejects_non_positive_timeout(capsys) -> None:
    rc = main(["ping", "--timeout", "0", "--key", "demo", "--port", "9000"])
    assert rc == 2
    assert "timeout must be positive" in capsys.readouterr().err


def test_cli_rejects_non_positive_max_frame_seconds(capsys) -> None:
    rc = main(["ping", "--max-frame-seconds", "0", "--key", "demo", "--port", "9000"])
    assert rc == 2
    assert "max-frame-seconds must be positive" in capsys.readouterr().err


def test_cli_inspect_missing_file_with_key_reports_hmac_invalid(capsys) -> None:
    rc = main(["inspect", str(FIXTURES / "missing.bin"), "--key", FIXTURE_KEY])
    assert rc == 3
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert report["hmac_valid"] is False


def test_whitespace_only_key_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)
    with pytest.raises(ValueError, match="provide --key"):
        _key_from_args(argparse.Namespace(key="   ", key_file=None))


def test_cli_rejects_non_positive_max_frame_size(capsys) -> None:
    rc = main(["ping", "--max-frame-size", "0", "--key", "demo", "--port", "9000"])
    assert rc == 2
    assert "max-frame-size must be at least 1" in capsys.readouterr().err


def test_cli_rejects_non_positive_idle_timeout(capsys) -> None:
    rc = main(["server", "--idle-timeout", "0", "--key", "demo"])
    assert rc == 2
    assert "idle-timeout must be positive" in capsys.readouterr().err


def test_cli_rejects_invalid_server_limits(capsys) -> None:
    rc = main(["server", "--max-connections", "0", "--key", "demo"])
    assert rc == 2
    assert "max-connections must be at least 1" in capsys.readouterr().err
    rc = main(["server", "--max-kv-keys", "0", "--key", "demo"])
    assert rc == 2
    assert "max-kv-keys must be at least 1" in capsys.readouterr().err
    rc = main(["server", "--max-malformed-frames", "0", "--key", "demo"])
    assert rc == 2
    assert "max-malformed-frames must be at least 1" in capsys.readouterr().err


def test_cli_server_bind_failure_reports_address_in_use(monkeypatch, capsys) -> None:
    def fail_bind(self: ToyProtoServer, *, ready: threading.Event | None = None) -> None:
        raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(ToyProtoServer, "serve_forever", fail_bind)
    rc = main(["server", "--host", "127.0.0.1", "--port", "9000", "--key", "demo"])
    assert rc == 3
    assert "address already in use" in capsys.readouterr().err


def test_interactive_unknown_command_is_non_fatal(monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def fake_input(_: str = "") -> str:
        calls["n"] += 1
        return "bogus" if calls["n"] == 1 else "quit"

    class StubClient:
        def ping(self) -> int:
            return 1

    monkeypatch.setattr("builtins.input", fake_input)
    _interactive(StubClient())  # type: ignore[arg-type]
    assert "unknown command: bogus" in capsys.readouterr().out


def test_interactive_put_without_value_shows_usage(monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def fake_input(_: str = "") -> str:
        calls["n"] += 1
        return "put lonely" if calls["n"] == 1 else "quit"

    class StubClient:
        def request(self, command: object, *args: str) -> object:
            raise AssertionError("request should not be called")

    monkeypatch.setattr("builtins.input", fake_input)
    _interactive(StubClient())  # type: ignore[arg-type]
    assert "usage: put KEY VALUE" in capsys.readouterr().out


def test_cli_missing_key_returns_usage_error(capsys, monkeypatch) -> None:
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)
    rc = main(["ping", "--port", "9000"])
    assert rc == 2
    assert "provide --key" in capsys.readouterr().err


def test_cli_connection_refused_returns_runtime_error(capsys, monkeypatch) -> None:
    monkeypatch.delenv("TOYPROTO_KEY", raising=False)

    def fail_connect(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr("toyproto.client.socket.create_connection", fail_connect)
    rc = main(["ping", "--key", "demo", "--port", "9000"])
    assert rc == 3
    assert "connection refused" in capsys.readouterr().err.lower()


def test_cli_protocol_error_returns_runtime_error(capsys, monkeypatch) -> None:
    import toyproto.cli as cli_module

    class FailingClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> FailingClient:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def ping(self) -> int:
            raise ProtocolError(ErrorCode.BAD_HMAC, "frame authentication failed")

    monkeypatch.setattr(cli_module, "ToyProtoClient", FailingClient)
    rc = main(["ping", "--key", "demo", "--port", "9000"])
    assert rc == 3
    assert "BAD_HMAC" in capsys.readouterr().err


def test_cli_reports_generic_oserror(capsys, monkeypatch) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise OSError("network down")

    monkeypatch.setattr("toyproto.client.socket.create_connection", fail_connect)
    rc = main(["ping", "--key", "demo", "--port", "9000"])
    assert rc == 3
    assert "network down" in capsys.readouterr().err


def test_cli_frame_hook_via_hexdump(capsys) -> None:
    server, thread = start_server()
    assert server.bound_port is not None
    try:
        rc = main(
            [
                "ping",
                "--host",
                "127.0.0.1",
                "--port",
                str(server.bound_port),
                "--key",
                "integration-key",
                "--hexdump",
            ]
        )
        assert rc == 0
        assert "[OUT]" in capsys.readouterr().err
    finally:
        stop_server(server, thread)


def test_interactive_continues_after_store_full(monkeypatch, capsys) -> None:
    calls = {"n": 0}

    def fake_input(_: str = "") -> str:
        calls["n"] += 1
        return "get missing" if calls["n"] == 1 else "quit"

    class StubClient:
        def request(self, command: object, *args: str) -> object:
            raise ProtocolError(ErrorCode.STORE_FULL, "full", fatal=False)

    monkeypatch.setattr("builtins.input", fake_input)
    _interactive(StubClient())  # type: ignore[arg-type]
    assert "error: STORE_FULL" in capsys.readouterr().err


def test_interactive_exits_on_eof(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError()))
    _interactive(type("C", (), {"ping": lambda self: 1})())  # type: ignore[arg-type]
    assert capsys.readouterr().out.endswith("\n")


def test_cli_inspect_rejects_invalid_max_frame_size(capsys) -> None:
    rc = main(["inspect", str(FIXTURES / "valid_hello.bin"), "--max-frame-size", "0"])
    assert rc == 2
    assert "max-frame-size must be at least 1" in capsys.readouterr().err


def test_interactive_runs_echo_time_get_delete(monkeypatch, capsys) -> None:
    lines = iter(["echo hi", "time", "get k", "delete k", "quit"])

    class StubClient:
        def request(self, command: object, *args: str) -> object:
            from toyproto.types import Response

            if command.name == "ECHO":
                return Response(command, (args[0],))
            if command.name == "TIME":
                return Response(command, ("2026-01-01T00:00:00Z",))
            if command.name == "KV_GET":
                return Response(command, ("v",))
            if command.name == "KV_DELETE":
                return Response(command, ("deleted",))
            raise AssertionError(command)

    monkeypatch.setattr("builtins.input", lambda _: next(lines))
    _interactive(StubClient())  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "hi" in out
    assert "2026-01-01T00:00:00Z" in out
    assert "v" in out
    assert "deleted" in out


def test_interactive_exits_on_toyproto_error(monkeypatch, capsys) -> None:
    from toyproto.errors import ToyProtoError

    monkeypatch.setattr("builtins.input", lambda _: "ping")
    _interactive(type("C", (), {"ping": lambda self: (_ for _ in ()).throw(ToyProtoError("boom"))})())  # type: ignore[arg-type]
    assert "error: boom" in capsys.readouterr().err


def test_cli_entrypoint_main_block(monkeypatch) -> None:
    import toyproto.cli as cli_module

    monkeypatch.setattr(cli_module, "main", lambda argv=None: 0)
    with pytest.raises(SystemExit) as exc:
        exec(compile("raise SystemExit(main())", "toyproto.cli", "exec"), cli_module.__dict__)
    assert exc.value.code == 0
