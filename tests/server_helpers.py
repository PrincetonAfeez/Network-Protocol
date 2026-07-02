"""Server helpers for ToyProto tests."""

from __future__ import annotations

import socket
import threading
from contextlib import suppress
from collections.abc import Callable

from toyproto.server import ToyProtoServer

KEY = b"integration-key"


def start_server(*, bind_port: int = 0, **kwargs: object) -> tuple[ToyProtoServer, threading.Thread]:
    options: dict[str, object] = {"header_timeout": 1.0, "body_timeout": 1.0}
    options.update(kwargs)
    server = ToyProtoServer("127.0.0.1", bind_port, KEY, **options)
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    return server, thread


def stop_server(server: ToyProtoServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(3)
    assert not thread.is_alive()


def one_shot_server(
    handler: Callable[[socket.socket], None],
    *,
    bind_port: int = 0,
) -> tuple[int, threading.Thread]:
    """Run ``handler`` for a single accepted TCP connection, then close."""
    ready = threading.Event()
    port_box: list[int] = []

    def run() -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", bind_port))
        listener.listen(1)
        port_box.append(listener.getsockname()[1])
        ready.set()
        connection, _ = listener.accept()
        try:
            handler(connection)
        finally:
            with suppress(OSError):
                connection.close()
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(3)
    return port_box[0], thread
