"""Thread-per-connection ToyProto server with a shared in-memory store."""

from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import suppress
from dataclasses import dataclass

from .app import ToyApplication
from .codec import decode_message, encode_message
from .constants import (
    BODY_TIMEOUT,
    CONTROL_REQUEST_ID,
    HEADER_SIZE,
    HEADER_TIMEOUT,
    IDLE_TIMEOUT,
    MAX_CONNECTIONS,
    MAX_FRAME_SECONDS,
    MAX_MALFORMED_FRAMES,
    MAX_FRAME_SIZE,
    MAX_KV_KEYS,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    ErrorCode,
)
from .errors import ConnectionClosed, ProtocolError
from .framing import encode_frame
from .state_machine import ConnectionState, Role, StateMachine
from .transport import RawFrameHook, read_frame, write_frame
from .types import Bye, ErrorMessage, Hello, HelloAck, Message, Ping, Pong, Request

LOGGER = logging.getLogger("toyproto.server")


@dataclass
class _ConnStats:
    frames_in: int = 0
    frames_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    errors: int = 0


@dataclass
class _Session:
    wire_version: int = PROTOCOL_VERSION


class ToyProtoServer:
    """Thread-per-connection ToyProto server with a shared in-memory store.

    Each accepted connection is handled on its own daemon thread. Resource use is
    bounded by ``max_connections`` (excess connections are refused immediately), a
    total per-frame read deadline in the transport, and the malformed-frame
    budget. The key-value store is shared across connections and lock-guarded.
    Per-connection frame/byte/error counts are logged when a connection closes.

    ``idle_timeout`` is the seconds a connection may wait for the first byte of
    a new frame. The deprecated ``timeout`` keyword is an alias for
    ``idle_timeout``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        key: bytes,
        *,
        idle_timeout: float = IDLE_TIMEOUT,
        timeout: float | None = None,
        header_timeout: float = HEADER_TIMEOUT,
        body_timeout: float = BODY_TIMEOUT,
        max_frame_size: int = MAX_FRAME_SIZE,
        max_frame_seconds: float = MAX_FRAME_SECONDS,
        max_malformed_frames: int = MAX_MALFORMED_FRAMES,
        max_connections: int = MAX_CONNECTIONS,
        max_kv_keys: int | None = None,
        frame_hook: RawFrameHook | None = None,
    ) -> None:
        if not key:
            raise ValueError("shared key must not be empty")
        if timeout is not None:
            idle_timeout = timeout
        if idle_timeout <= 0:
            raise ValueError("idle_timeout must be positive")
        if header_timeout <= 0:
            raise ValueError("header_timeout must be positive")
        if body_timeout <= 0:
            raise ValueError("body_timeout must be positive")
        if max_frame_seconds <= 0:
            raise ValueError("max_frame_seconds must be positive")
        if max_frame_size < 1:
            raise ValueError("max_frame_size must be at least 1")
        if max_kv_keys is not None and max_kv_keys < 1:
            raise ValueError("max_kv_keys must be at least 1")
        self.host = host
        self.port = port
        self.key = key
        self.idle_timeout = idle_timeout
        self.header_timeout = header_timeout
        self.body_timeout = body_timeout
        self.max_frame_size = max_frame_size
        self.max_frame_seconds = max_frame_seconds
        if max_malformed_frames < 1:
            raise ValueError("max_malformed_frames must be at least 1")
        self.max_malformed_frames = max_malformed_frames
        if max_connections < 1:
            raise ValueError("max_connections must be at least 1")
        self.max_connections = max_connections
        self._slots = threading.BoundedSemaphore(max_connections)
        self.frame_hook = frame_hook
        self.application = ToyApplication(max_keys=max_kv_keys if max_kv_keys is not None else MAX_KV_KEYS)
        self._listener: socket.socket | None = None
        self._stop = threading.Event()
        self._threads: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._threads_lock = threading.Lock()
        self._local = threading.local()
        self.bound_port: int | None = None

    def serve_forever(self, *, ready: threading.Event | None = None) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen()
        listener.settimeout(0.5)
        self._listener = listener
        self.bound_port = listener.getsockname()[1]
        LOGGER.info("listening on %s:%s", self.host, self.bound_port)
        if ready:
            ready.set()
        try:
            while not self._stop.is_set():
                try:
                    connection, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError as exc:
                    if self._stop.is_set():
                        break
                    # Transient accept failures (e.g. EMFILE) must not kill the
                    # accept loop; log and back off briefly instead of crashing.
                    LOGGER.warning("accept failed, continuing: %s", exc)
                    self._stop.wait(0.1)
                    continue
                # Disable Nagle: this is a small request/response protocol, so we
                # want each frame on the wire immediately rather than coalesced.
                with suppress(OSError):
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if not self._slots.acquire(blocking=False):
                    LOGGER.warning(
                        "at capacity (%d connections); refusing %s:%s",
                        self.max_connections,
                        *address,
                    )
                    with suppress(OSError):
                        connection.close()
                    continue
                thread = threading.Thread(
                    target=self._handle_connection_guarded,
                    args=(connection, address),
                    daemon=True,
                )
                with self._threads_lock:
                    self._threads.add(thread)
                    self._connections.add(connection)
                thread.start()
        finally:
            with suppress(OSError):
                listener.close()
            self._listener = None
            self._close_active_connections()
            self._join_connections()
            LOGGER.info("server stopped")

    def _join_connections(self) -> None:
        with self._threads_lock:
            threads = tuple(self._threads)
        for thread in threads:
            thread.join(timeout=2)

    def shutdown(self) -> None:
        self._stop.set()
        listener = self._listener
        if listener is not None:
            with suppress(OSError):
                listener.close()
        self._close_active_connections()

    def _close_active_connections(self) -> None:
        # Unblock handlers parked in a blocking recv so they observe the stop
        # flag and tear down promptly instead of lingering until their idle or
        # read timeout fires. Shutting the socket wakes recv with EOF; each
        # handler's own finally still performs the close.
        with self._threads_lock:
            connections = tuple(self._connections)
        for connection in connections:
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)

    def _handle_connection_guarded(
        self,
        connection: socket.socket,
        address: tuple[str, int],
    ) -> None:
        try:
            self._handle_connection(connection, address)
        except Exception:
            LOGGER.exception("unexpected connection handler failure for %s:%s", *address)
        finally:
            self._slots.release()
            with self._threads_lock:
                self._threads.discard(threading.current_thread())
                self._connections.discard(connection)

    def _send(
        self,
        connection: socket.socket,
        state: StateMachine,
        message: Message,
        request_id: int,
        session: _Session,
    ) -> None:
        message_type, body = encode_message(message)
        state.on_send(message_type)
        raw = encode_frame(
            self.key,
            message_type,
            request_id,
            body,
            version=session.wire_version,
            max_frame_size=self.max_frame_size,
        )
        LOGGER.debug("send %s request_id=%s", message_type.name, request_id)
        write_frame(connection, raw, hook=self.frame_hook)
        stats = getattr(self._local, "stats", None)
        if stats is not None:
            stats.frames_out += 1
            stats.bytes_out += len(raw)

    def _send_error(
        self,
        connection: socket.socket,
        state: StateMachine,
        request_id: int,
        error: ProtocolError,
        session: _Session,
    ) -> None:
        try:
            self._send(connection, state, ErrorMessage(error.code, error.reason), request_id, session)
        except (ConnectionClosed, ProtocolError, OSError):
            LOGGER.debug("could not send ERROR frame", exc_info=True)

    def _handle_connection(
        self,
        connection: socket.socket,
        address: tuple[str, int],
    ) -> None:
        LOGGER.info("accepted %s:%s", *address)
        state = StateMachine(Role.SERVER)
        session = _Session()
        stats = _ConnStats()
        self._local.stats = stats
        started = time.monotonic()
        malformed_frames = 0
        connection.settimeout(self.idle_timeout)
        try:
            while not self._stop.is_set() and state.state is not ConnectionState.CLOSED:
                current_request_id = CONTROL_REQUEST_ID
                try:
                    frame = read_frame(
                        connection,
                        self.key,
                        max_frame_size=self.max_frame_size,
                        header_timeout=self.header_timeout,
                        body_timeout=self.body_timeout,
                        idle_timeout=self.idle_timeout,
                        max_frame_seconds=self.max_frame_seconds,
                        hook=self.frame_hook,
                    )
                    stats.frames_in += 1
                    stats.bytes_in += HEADER_SIZE + len(frame.body)
                    current_request_id = frame.request_id
                    state.on_receive(frame.message_type)
                    message = decode_message(frame.message_type, frame.body)
                    LOGGER.debug(
                        "receive %s request_id=%s from %s:%s",
                        frame.message_type.name,
                        frame.request_id,
                        *address,
                    )
                    should_close = self._dispatch(connection, state, frame.request_id, message, session)
                    if should_close:
                        break
                except ConnectionClosed:
                    break
                except ProtocolError as exc:
                    LOGGER.warning("protocol error from %s:%s: %s", *address, exc)
                    stats.errors += 1
                    if exc.fatal:
                        # Frame integrity or authenticity is unknown: close at
                        # once without replying. Fatal errors never count toward
                        # the malformed-frame budget because they always close.
                        break
                    # Nonfatal connection-level error (e.g. malformed body, wrong
                    # state): answer with an ERROR and count it. The connection
                    # closes once these reach max_malformed_frames.
                    self._send_error(connection, state, current_request_id, exc, session)
                    malformed_frames += 1
                    if malformed_frames >= self.max_malformed_frames:
                        break
                except Exception:
                    LOGGER.exception("internal error while handling %s:%s", *address)
                    stats.errors += 1
                    self._send_error(
                        connection,
                        state,
                        current_request_id,
                        ProtocolError(
                            ErrorCode.INTERNAL_ERROR,
                            "internal server error",
                            fatal=False,
                        ),
                        session,
                    )
                    break
        finally:
            state.close()
            with suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()
            LOGGER.info(
                "closed %s:%s frames_in=%d frames_out=%d bytes_in=%d bytes_out=%d "
                "errors=%d duration=%.3fs",
                *address,
                stats.frames_in,
                stats.frames_out,
                stats.bytes_in,
                stats.bytes_out,
                stats.errors,
                time.monotonic() - started,
            )

    def _dispatch(
        self,
        connection: socket.socket,
        state: StateMachine,
        request_id: int,
        message: Message,
        session: _Session,
    ) -> bool:
        if isinstance(message, Hello):
            if request_id != CONTROL_REQUEST_ID:
                raise ProtocolError(ErrorCode.MALFORMED_BODY, "HELLO request_id must be 0")
            compatible = [v for v in message.supported_versions if v in SUPPORTED_VERSIONS]
            if not compatible:
                error = ProtocolError(
                    ErrorCode.UNSUPPORTED_VERSION,
                    f"no shared version; server supports {SUPPORTED_VERSIONS}",
                    fatal=False,
                )
                self._send_error(connection, state, CONTROL_REQUEST_ID, error, session)
                return True
            selected = max(compatible)
            session.wire_version = selected
            self._send(
                connection,
                state,
                HelloAck(selected),
                CONTROL_REQUEST_ID,
                session,
            )
            return False
        if isinstance(message, Ping):
            if request_id != CONTROL_REQUEST_ID:
                raise ProtocolError(ErrorCode.MALFORMED_BODY, "PING request_id must be 0")
            self._send(connection, state, Pong(message.nonce), CONTROL_REQUEST_ID, session)
            return False
        if isinstance(message, Request):
            if request_id == CONTROL_REQUEST_ID:
                raise ProtocolError(ErrorCode.MALFORMED_BODY, "REQUEST request_id must be nonzero")
            try:
                response = self.application.execute(message)
            except ProtocolError as exc:
                self._send_error(connection, state, request_id, exc, session)
            else:
                self._send(connection, state, response, request_id, session)
            return False
        if isinstance(message, Bye):
            if request_id != CONTROL_REQUEST_ID:
                raise ProtocolError(ErrorCode.MALFORMED_BODY, "BYE request_id must be 0")
            self._send(connection, state, Bye("goodbye"), CONTROL_REQUEST_ID, session)
            return True
        # Forward-defensive: the state machine only admits HELLO/PING/REQUEST/BYE
        # to the server, all handled above, so this is unreachable in practice.
        raise ProtocolError(  # pragma: no cover
            ErrorCode.BAD_STATE,
            f"server cannot handle {type(message).__name__} from client",
            fatal=False,
        )
