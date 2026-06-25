from __future__ import annotations

import threading

from toyproto.server import ToyProtoServer

KEY = b"integration-key"


def start_server(**kwargs: object) -> tuple[ToyProtoServer, threading.Thread]:
    server = ToyProtoServer("127.0.0.1", 0, KEY, header_timeout=1.0, body_timeout=1.0, **kwargs)
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_forever, kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(3)
    return server, thread


def stop_server(server: ToyProtoServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(3)
    assert not thread.is_alive()
