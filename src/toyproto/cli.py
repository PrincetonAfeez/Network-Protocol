"""Thin argparse command-line interface."""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .client import ToyProtoClient
from .constants import (
    APPLICATION_ERROR_CODES,
    HEADER_SIZE,
    IDLE_TIMEOUT,
    MAX_CONNECTIONS,
    MAX_FRAME_SECONDS,
    MAX_FRAME_SIZE,
    MAX_KV_KEYS,
    Command,
)
from .errors import ConnectionClosed, ProtocolError, ToyProtoError
from .hexdump import describe_raw_frame
from .inspect import inspect_file
from .server import ToyProtoServer


def _add_connection_options(parser: argparse.ArgumentParser, *, for_server: bool = False) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--key", help="shared key (local testing only)")
    parser.add_argument("--key-file", type=Path, help="file containing the shared key")
    if for_server:
        parser.add_argument(
            "--timeout",
            type=float,
            default=5.0,
            help="per-read timeout for header and body bytes once a frame begins (default 5)",
        )
    else:
        parser.add_argument(
            "--timeout",
            type=float,
            default=5.0,
            help=(
                "TCP connect timeout and per-read budget for idle, header, and body "
                "waits on the client (default 5)"
            ),
        )
    parser.add_argument("--max-frame-size", type=int, default=MAX_FRAME_SIZE)
    if not for_server:
        parser.add_argument(
            "--max-frame-seconds",
            type=float,
            default=MAX_FRAME_SECONDS,
            help="total wall-clock budget to assemble one inbound frame (default 30)",
        )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--hexdump", action="store_true", help="print raw frames")


def _key_from_args(args: argparse.Namespace, *, required: bool = True) -> bytes | None:
    candidates = [
        args.key.encode() if getattr(args, "key", None) else None,
        args.key_file.read_bytes() if getattr(args, "key_file", None) else None,
        os.environ.get("TOYPROTO_KEY", "").encode() or None,
    ]
    key = next((candidate for candidate in candidates if candidate), None)
    # Keys are treated as UTF-8 text: surrounding whitespace is stripped from
    # every source uniformly so the same secret matches however it is supplied
    # (e.g. a key file written with a trailing newline vs. an inline --key).
    if key is not None:
        key = key.strip()
    if required and not key:
        raise ValueError("provide --key, --key-file, or TOYPROTO_KEY")
    return key


def _frame_hook(direction: str, data: bytes) -> None:
    print(f"\n[{direction}] {describe_raw_frame(data)}", file=sys.stderr)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toyproto",
        description="ToyProto framed TCP lab",
        epilog="exit codes: 0 success; 2 usage or runtime/protocol error; 130 interrupted (Ctrl-C)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    server = subparsers.add_parser("server", help="run the TCP server")
    _add_connection_options(server, for_server=True)
    server.add_argument("--max-malformed-frames", type=int, default=1)
    server.add_argument(
        "--idle-timeout",
        type=float,
        default=IDLE_TIMEOUT,
        help="seconds a connection may sit idle between frames (default 60)",
    )
    server.add_argument(
        "--max-connections",
        type=int,
        default=MAX_CONNECTIONS,
        help="maximum concurrent connections (default 64)",
    )
    server.add_argument(
        "--max-kv-keys",
        type=int,
        default=MAX_KV_KEYS,
        help="maximum distinct keys in the in-memory store (default 1024)",
    )
    server.add_argument(
        "--max-frame-seconds",
        type=float,
        default=MAX_FRAME_SECONDS,
        help="total wall-clock budget to assemble one frame (default 30)",
    )

    client = subparsers.add_parser("client", help="open an interactive client")
    _add_connection_options(client)

    for name, help_text in (
        ("ping", "send PING and expect PONG"),
        ("time", "request the server UTC time"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_connection_options(command)

    echo = subparsers.add_parser("echo", help="echo text through the server")
    echo.add_argument("text")
    _add_connection_options(echo)

    put = subparsers.add_parser("put", help="store an in-memory key/value")
    put.add_argument("key_name")
    put.add_argument("value")
    _add_connection_options(put)

    get = subparsers.add_parser("get", help="retrieve an in-memory value")
    get.add_argument("key_name")
    _add_connection_options(get)

    delete = subparsers.add_parser("delete", help="delete an in-memory key")
    delete.add_argument("key_name")
    _add_connection_options(delete)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a saved binary frame")
    inspect_parser.add_argument("path", type=Path)
    inspect_parser.add_argument("--key")
    inspect_parser.add_argument("--key-file", type=Path)
    inspect_parser.add_argument("--max-frame-size", type=int, default=MAX_FRAME_SIZE)

    hex_parser = subparsers.add_parser("hexdump", help="hexdump a saved binary frame")
    hex_parser.add_argument("path", type=Path)
    return parser


def _validate_runtime_args(args: argparse.Namespace) -> None:
    if getattr(args, "timeout", None) is not None and args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    max_frame_seconds = getattr(args, "max_frame_seconds", None)
    if max_frame_seconds is not None and max_frame_seconds <= 0:
        raise ValueError("--max-frame-seconds must be positive")
    max_frame_size = getattr(args, "max_frame_size", None)
    if max_frame_size is not None and max_frame_size < 1:
        raise ValueError("--max-frame-size must be at least 1")
    idle_timeout = getattr(args, "idle_timeout", None)
    if idle_timeout is not None and idle_timeout <= 0:
        raise ValueError("--idle-timeout must be positive")
    max_malformed = getattr(args, "max_malformed_frames", None)
    if max_malformed is not None and max_malformed < 1:
        raise ValueError("--max-malformed-frames must be at least 1")
    max_connections = getattr(args, "max_connections", None)
    if max_connections is not None and max_connections < 1:
        raise ValueError("--max-connections must be at least 1")
    max_kv_keys = getattr(args, "max_kv_keys", None)
    if max_kv_keys is not None and max_kv_keys < 1:
        raise ValueError("--max-kv-keys must be at least 1")


def _client_for(args: argparse.Namespace) -> ToyProtoClient:
    key = _key_from_args(args)
    assert key is not None
    return ToyProtoClient(
        args.host,
        args.port,
        key,
        timeout=args.timeout,
        max_frame_size=args.max_frame_size,
        max_frame_seconds=args.max_frame_seconds,
        frame_hook=_frame_hook if args.hexdump else None,
    )


def _interactive(client: ToyProtoClient) -> None:
    print(
        "Connected. Commands: ping, echo TEXT, time, put KEY VALUE, get KEY, delete KEY, quit\n"
        "Note: the server closes idle connections after its --idle-timeout (default 60s). "
        "Raise it when pausing at this prompt, e.g. toyproto server --idle-timeout 3600."
    )
    while True:
        try:
            line = input("toyproto> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        name, _, rest = line.partition(" ")
        if name in {"quit", "exit", "bye"}:
            break
        try:
            if name == "ping":
                print(f"PONG {client.ping()}")
            elif name == "echo":
                print(client.request(Command.ECHO, rest).values[0])
            elif name == "time":
                print(client.request(Command.TIME).values[0])
            elif name == "put":
                key, separator, value = rest.partition(" ")
                if not separator:
                    print("usage: put KEY VALUE")
                    continue
                print(client.request(Command.KV_PUT, key, value).values[0])
            elif name == "get":
                print(client.request(Command.KV_GET, rest).values[0])
            elif name == "delete":
                print(client.request(Command.KV_DELETE, rest).values[0])
            else:
                print(f"unknown command: {name}")
        except ConnectionClosed as exc:
            print(f"connection closed: {exc}", file=sys.stderr)
            break
        except ProtocolError as exc:
            print(f"error: {exc}", file=sys.stderr)
            if exc.code not in APPLICATION_ERROR_CODES:
                break
        except ToyProtoError as exc:
            print(f"error: {exc}", file=sys.stderr)
            break


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    try:
        if args.command == "server":
            _validate_runtime_args(args)
            key = _key_from_args(args)
            assert key is not None
            server = ToyProtoServer(
                args.host,
                args.port,
                key,
                idle_timeout=args.idle_timeout,
                header_timeout=args.timeout,
                body_timeout=args.timeout,
                max_frame_size=args.max_frame_size,
                max_frame_seconds=args.max_frame_seconds,
                max_malformed_frames=args.max_malformed_frames,
                max_connections=args.max_connections,
                max_kv_keys=args.max_kv_keys,
                frame_hook=_frame_hook if args.hexdump else None,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                server.shutdown()
            return 0

        if args.command == "inspect":
            _validate_runtime_args(args)
            key = _key_from_args(args, required=False)
            report = inspect_file(args.path, key=key, max_frame_size=args.max_frame_size)
            print(json.dumps(report, indent=2, default=str))
            return 0 if report.get("valid") else 2

        if args.command == "hexdump":
            cap = HEADER_SIZE + MAX_FRAME_SIZE
            try:
                with args.path.open("rb") as handle:
                    data = handle.read(cap + 1)
            except OSError as exc:
                print(f"toyproto: cannot read {args.path}: {exc}", file=sys.stderr)
                return 2
            if len(data) > cap:
                print(
                    f"toyproto: {args.path} is larger than a single frame ({cap} bytes)",
                    file=sys.stderr,
                )
                return 2
            print(describe_raw_frame(data))
            return 0

        _validate_runtime_args(args)
        with _client_for(args) as client:
            if args.command == "client":
                _interactive(client)
            elif args.command == "ping":
                print(f"PONG {client.ping()}")
            elif args.command == "echo":
                print(client.request(Command.ECHO, args.text).values[0])
            elif args.command == "time":
                print(client.request(Command.TIME).values[0])
            elif args.command == "put":
                print(client.request(Command.KV_PUT, args.key_name, args.value).values[0])
            elif args.command == "get":
                print(client.request(Command.KV_GET, args.key_name).values[0])
            elif args.command == "delete":
                print(client.request(Command.KV_DELETE, args.key_name).values[0])
        return 0
    except KeyboardInterrupt:
        print("toyproto: interrupted", file=sys.stderr)
        return 130
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.EADDRINUSE:
            host = getattr(args, "host", "127.0.0.1")
            port = getattr(args, "port", "?")
            print(f"toyproto: address already in use ({host}:{port})", file=sys.stderr)
            return 2
        print(f"toyproto: {exc}", file=sys.stderr)
        return 2
    except (ValueError, ToyProtoError) as exc:
        print(f"toyproto: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
