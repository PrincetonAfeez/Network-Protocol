"""Thin argparse command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .client import ToyProtoClient
from .constants import HEADER_SIZE, IDLE_TIMEOUT, MAX_CONNECTIONS, MAX_FRAME_SIZE, Command
from .errors import ConnectionClosed, ToyProtoError
from .hexdump import describe_raw_frame
from .inspect import inspect_file
from .server import ToyProtoServer


def _add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--key", help="shared key (local testing only)")
    parser.add_argument("--key-file", type=Path, help="file containing the shared key")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-frame-size", type=int, default=MAX_FRAME_SIZE)
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
    _add_connection_options(server)
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


def _client_for(args: argparse.Namespace) -> ToyProtoClient:
    key = _key_from_args(args)
    assert key is not None
    return ToyProtoClient(
        args.host,
        args.port,
        key,
        timeout=args.timeout,
        max_frame_size=args.max_frame_size,
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
        except ToyProtoError as exc:
            print(f"error: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    try:
        if args.command == "server":
            key = _key_from_args(args)
            assert key is not None
            server = ToyProtoServer(
                args.host,
                args.port,
                key,
                idle_timeout=max(args.idle_timeout, 0.1),
                header_timeout=args.timeout,
                body_timeout=args.timeout,
                max_frame_size=args.max_frame_size,
                max_malformed_frames=args.max_malformed_frames,
                max_connections=args.max_connections,
                frame_hook=_frame_hook if args.hexdump else None,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                server.shutdown()
            return 0

        if args.command == "inspect":
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
    except (OSError, ValueError, ToyProtoError) as exc:
        print(f"toyproto: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
