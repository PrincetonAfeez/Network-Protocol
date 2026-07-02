# Architecture Decision Records
 
These compact ADRs record the design choices behind ToyProto.

## ADR-001: CLI first

Accepted. A CLI keeps the protocol bytes, lifecycle, and failure modes visible.
A web UI would add a second protocol and obscure the capstone's main subject.

## ADR-002: Django and HTMX are stretch only

Accepted. A future read-only inspector could use them, but they are not needed
to prove framing, parsing, authentication, or state enforcement.

## ADR-003: Raw TCP sockets

Accepted. Raw sockets expose partial reads, stream boundaries, timeout behavior,
and teardown directly—the systems concepts this project intends to exercise.

## ADR-004: Length-prefixed framing

Accepted. A fixed header gives deterministic parsing and permits the receiver
to reject excessive lengths before reading a body.

## ADR-005: Explicit network byte order

Accepted. `struct` format `!4sBBHQI32s` is portable and makes every field width
and byte order part of the contract.

## ADR-006: Pure codec

Accepted. Message encoding and decoding perform no I/O or application work.
This makes hostile parser tests fast, deterministic, and exhaustive.

## ADR-007: HMAC-SHA256

Accepted. A pre-shared-key HMAC demonstrates integrity and authenticity with a
standard primitive and constant-time verification.

## ADR-008: Zeroed tag slot

Accepted. Authenticating the complete header shape with a zeroed HMAC field
avoids circularity while protecting all other header fields.

## ADR-009: No confidentiality

Accepted. Encryption and key establishment are outside scope. Documentation
states plainly that payloads remain visible on the wire.

## ADR-010: Explicit state machine

Accepted. Authentication alone cannot stop a valid message arriving at an
invalid point in the lifecycle; state validation precedes application work.

## ADR-011: Pre-allocation size enforcement

Accepted. `BODY_LEN` is checked from the fixed header before any body read,
preventing an attacker-controlled large allocation.

## ADR-012: Fixtures and fuzz tests

Accepted. Reproducible hostile bytes document the format, while random-byte
tests verify that parser failures remain controlled exceptions.

## ADR-013: No sequence numbers in version 1

Accepted with known risk. Version 1 has no replay prevention. Sequence numbers
would require session identity and persistence semantics that distract from the
core framing exercise; they are a clear next version.

## ADR-014: Thread-per-connection concurrency

Accepted with known limits. The server handles each accepted connection on its
own daemon thread. This keeps per-connection logic sequential and easy to read,
which suits the teaching goal; concurrency is not the subject under study.

Shared state is minimal and guarded: the key-value store has its own lock, the
live-thread and live-connection sets share one lock, and per-connection
statistics live in a `threading.local` so handlers never share counters. No
operation holds more than one of these locks at a time and there is no nested
acquisition, so lock-ordering deadlock cannot arise.

Starvation/exhaustion is the genuine risk of one-thread-per-connection: many
connections, or slow-read ("dribble") peers, could otherwise tie up threads
indefinitely. Two limits bound it — a concurrent-connection cap
(`MAX_CONNECTIONS`; connections beyond it are refused immediately) and a total
per-frame read deadline (`MAX_FRAME_SECONDS`) that drops peers stalling in
aggregate, not just per read. Cancellation uses a stop `Event` plus
`shutdown(SHUT_RDWR)` on live sockets to wake blocked reads, since Python threads
cannot be force-cancelled.

An `asyncio` rewrite would scale to far more connections but is out of scope (a
listed stretch goal); the synchronous model is sufficient and clearer here.

