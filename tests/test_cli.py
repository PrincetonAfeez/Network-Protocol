from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

import pytest

from toyproto import __version__
from toyproto.cli import _interactive, _key_from_args, build_parser, main
from toyproto.constants import IDLE_TIMEOUT
from toyproto.errors import ConnectionClosed

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


def test_cli_inspect_bad_fixture_returns_two(capsys) -> None:
    rc = main(["inspect", str(FIXTURES / "bad_magic.bin"), "--key", FIXTURE_KEY])
    assert rc == 2
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert "error" in report


def test_cli_hexdump_renders_header_fields(capsys) -> None:
    rc = main(["hexdump", str(FIXTURES / "valid_ping.bin")])
    assert rc == 0
    assert "magic:" in capsys.readouterr().out


def test_cli_hexdump_missing_file_returns_two(capsys) -> None:
    rc = main(["hexdump", str(FIXTURES / "does_not_exist_98765.bin")])
    assert rc == 2
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
    assert rc == 2
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
