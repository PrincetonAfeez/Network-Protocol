# Architecture Decision Record
## App — Network Protocol
**Binary Protocol Systems Group | Document 1 of 5**
**Status: Accepted**

---

## Context

The Binary Protocol Systems group requires a portfolio-ready networking capstone that demonstrates how an application protocol is designed directly on top of TCP. The project must show byte-level framing, exact reads, binary body schemas, authentication tags, version negotiation, client/server state machines, bounded resource usage, diagnostic frame inspection, and loopback/offline verification.

The project is named **ToyProto Lab**. It is a CLI-first framed binary application protocol over raw TCP sockets. It is intentionally small enough to audit byte by byte and intentionally defensive enough to demonstrate hostile-input systems programming. It is not HTTP, TLS, WebSockets, gRPC, a production identity system, an encrypted transport, or a replay-proof messaging system.

The selected architecture uses a fixed 52-byte header, length-prefixed bodies, a pure binary codec, HMAC-SHA256 authentication over canonical frame bytes, exact socket reads, client/server connection state machines, a thread-per-connection server, and a small lock-guarded in-memory key-value application.

---

## Decisions

### Decision 1 — Build a binary TCP protocol instead of HTTP

**Chosen:** Implement a custom framed binary protocol directly over TCP.

**Rejected:** HTTP, WebSockets, gRPC, or a web framework.

**Reason:** The capstone goal is to learn protocol mechanics: framing, byte order, exact reads, body lengths, authentication bytes, socket timeouts, and state machines. HTTP would hide too much of that work.

---

### Decision 2 — Treat TCP as a byte stream, not a message system

**Chosen:** Implement `read_exact()` and explicit frame assembly.

**Rejected:** Assuming one `recv()` equals one frame.

**Reason:** TCP can return partial headers, partial bodies, or multiple frames worth of bytes. The protocol must define and enforce framing itself.

---

### Decision 3 — Use a fixed 52-byte header

**Chosen:** Header fields are fixed and packed with network byte order.

Header fields:
- magic
- protocol version
- message type
- flags
- request ID
- body length
- HMAC tag

**Rejected:** Text headers or variable-length metadata.

**Reason:** A fixed header is easy to inspect, validate before allocation, and teach byte by byte.

---

### Decision 4 — Length-prefix every body

**Chosen:** `BODY_LEN` declares the exact body length.

**Rejected:** Delimiters, newline framing, or EOF-terminated messages.

**Reason:** Binary bodies can contain arbitrary bytes. A length prefix allows exact reads and early rejection of oversized frames.

---

### Decision 5 — Validate header before reading body

**Chosen:** Parse and validate magic, version, type, flags, and body length before body allocation/read.

**Rejected:** Reading body first and validating later.

**Reason:** A hostile peer could declare an enormous body. The reader must reject over-limit lengths before reading or allocating the body.

---

### Decision 6 — Use HMAC-SHA256 for frame authenticity/integrity

**Chosen:** Authenticate the complete header with its tag slot zeroed plus the exact body.

**Rejected:** No authentication, checksum only, or encrypting traffic.

**Reason:** HMAC demonstrates shared-key authenticity and tamper detection without pretending to provide confidentiality. `hmac.compare_digest` prevents timing-sensitive comparisons.

---

### Decision 7 — Explicitly state HMAC limits

**Chosen:** Document that HMAC does not encrypt data, does not provide identity beyond possession of the shared key, and does not prevent replay.

**Rejected:** Calling the protocol “secure” in a production sense.

**Reason:** Honest security boundaries matter. This protocol teaches authentication, not TLS or a full security model.

---

### Decision 8 — Keep the codec pure

**Chosen:** Body encode/decode functions know nothing about sockets, environment variables, server state, or application storage.

**Rejected:** Combining codec, transport, and app behavior.

**Reason:** A pure codec is easier to test, fuzz, inspect, and reason about. It can reject malformed bodies without side effects.

---

### Decision 9 — Use explicit schemas per opcode

**Chosen:** Each message type and command has a known schema, bounded string lengths, strict UTF-8, known enum values, and no trailing bytes.

**Rejected:** JSON bodies or unstructured payload blobs.

**Reason:** Binary protocols require discipline. Explicit schemas make malformed inputs detectable.

---

### Decision 10 — Implement version negotiation

**Chosen:** Client sends `HELLO` with supported versions, server replies `HELLO_ACK` with the selected shared version.

**Rejected:** Hard-coding version silently with no handshake.

**Reason:** Even a one-version protocol should show how version negotiation would work and how unsupported versions fail.

---

### Decision 11 — Enforce state machines on both endpoints

**Chosen:** Client and server each own a role-specific state machine.

**Rejected:** Letting any valid frame appear in any order.

**Reason:** A structurally valid frame can still be illegal before handshake or after close. Protocol correctness requires stateful validation.

---

### Decision 12 — Reserve request ID 0 for control frames

**Chosen:** `HELLO`, `PING`, `PONG`, and `BYE` use request ID 0. Application `REQUEST` frames must use nonzero request IDs.

**Rejected:** Letting all frames use arbitrary IDs.

**Reason:** Separating control traffic from application request/response traffic makes validation and debugging clearer.

---

### Decision 13 — Check response request IDs

**Chosen:** The client rejects a `RESPONSE` whose request ID does not match the request.

**Rejected:** Accepting the next response blindly.

**Reason:** Request IDs are part of the protocol contract. Even synchronous request/response behavior should protect against mismatched frames.

---

### Decision 14 — Use synchronous request/response behavior

**Chosen:** One-shot client commands open a connection, handshake, send a request, read a response, and close.

**Rejected:** Multiplexing, pipelining, or asynchronous streams.

**Reason:** The capstone already covers protocol fundamentals. Multiplexing would complicate request tracking and concurrency without being necessary for V1.

---

### Decision 15 — Use a thread-per-connection server with a hard cap

**Chosen:** Each accepted connection runs on a daemon thread, guarded by a bounded semaphore.

**Rejected:** Unbounded threads or a fully asynchronous server.

**Reason:** Thread-per-connection is understandable and appropriate for a small loopback lab, but it must be capped to avoid unbounded resource use.

---

### Decision 16 — Close excess connections immediately

**Chosen:** If the server is at capacity, it closes the accepted socket without a protocol response.

**Rejected:** Queueing indefinitely or trying to send a framed error while overloaded.

**Reason:** Capacity protection is a resource-control boundary. When no handler slot exists, the server should release the connection quickly.

---

### Decision 17 — Use total per-frame read deadlines

**Chosen:** In addition to per-recv timeouts, a total `max_frame_seconds` bounds frame assembly after the first byte arrives.

**Rejected:** Only per-read socket timeouts.

**Reason:** A slow-dribble peer can stay under per-read timeout forever. A total deadline closes that attack path.

---

### Decision 18 — Keep the app tiny and in memory

**Chosen:** Implement `ECHO`, `TIME`, `KV_PUT`, `KV_GET`, and `KV_DELETE` with an in-memory store.

**Rejected:** Database persistence or a web API.

**Reason:** The application exists to exercise protocol request/response behavior. Persistence would distract from binary protocol design.

---

### Decision 19 — Bound key-value store size

**Chosen:** The in-memory store has a maximum key count.

**Rejected:** Unlimited dictionary growth.

**Reason:** Even demo protocols need explicit memory bounds.

---

### Decision 20 — Provide offline frame inspection tools

**Chosen:** Ship `toyproto inspect` and `toyproto hexdump`.

**Rejected:** Requiring a live server to understand frames.

**Reason:** A binary protocol should be auditable offline. Inspectors help reviewers see structure, HMAC validity, and decoded bodies.

---

## Consequences

**Positive:**
- The project demonstrates raw TCP protocol fundamentals.
- Frame format is byte-auditable.
- Codec behavior is pure and testable.
- Header validation prevents oversized body reads.
- HMAC protects integrity/authenticity under a shared key.
- State machines reject legal-looking frames in illegal phases.
- Exact-read transport handles TCP correctly.
- Total frame deadlines defend against slow-dribble peers.
- Diagnostic tools make binary frames inspectable.
- Loopback and offline tests cover realistic failure cases.

**Negative / Trade-offs:**
- No encryption.
- No replay protection.
- No production identity model.
- Shared-key compromise means any holder can forge frames.
- Server state is memory-only.
- IPv4 only.
- Thread-per-connection does not scale like async I/O.
- No multiplexing or pipelining.
- No HTTP/web layer.

---

## Alternatives Not Explored

- TLS transport.
- Replay nonce cache.
- Public-key signatures.
- mTLS or certificate identity.
- Asyncio server.
- UDP transport.
- HTTP/2, WebSockets, or gRPC.
- Multiplexed streams.
- Persistent database app.
- Dynamic extension opcodes.
- Compression.
- Binary schema language such as Protobuf or FlatBuffers.

---

*Constitution reference: Article 1 (Python fundamentals and architectural thinking), Article 3.3 (scope discipline), Article 4 (quality proportional to scope), Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity).*

---


# Technical Design Document
## App — Network Protocol
**Binary Protocol Systems Group | Document 2 of 5**

---

## Overview

ToyProto Lab is a defensive framed binary protocol over TCP. It provides a CLI, client, server, pure codec, HMAC-authenticated framing, exact-read transport, state machines, a small in-memory key-value app, and offline frame inspection tools.

**Package:** `toyproto-lab`  
**Import module:** `toyproto`  
**Console command:** `toyproto`  
**Python:** `>=3.11`  
**Runtime dependencies:** none  
**Protocol version:** `1`  
**Header size:** `52` bytes  
**Default max body:** `1 MiB`  
**Default server idle timeout:** `60s`  
**Default per-read timeout:** `5s`  
**Default total frame deadline:** `30s`

---

## System Context

```text
toyproto CLI
  │
  ├── server command
  │     └── ToyProtoServer
  │          ├── TCP listener
  │          ├── thread per connection
  │          ├── StateMachine(Role.SERVER)
  │          ├── exact-read transport
  │          ├── framing + HMAC
  │          ├── pure codec
  │          └── ToyApplication
  │
  ├── one-shot client commands
  │     └── ToyProtoClient
  │          ├── TCP connect
  │          ├── StateMachine(Role.CLIENT)
  │          ├── HELLO / HELLO_ACK
  │          ├── request / response
  │          └── graceful BYE
  │
  └── offline tools
        ├── inspect
        └── hexdump
```

---

## Main Package Areas

```text
src/toyproto/
  __init__.py       # public exports and package version
  constants.py      # wire constants, opcodes, limits, error codes
  types.py          # typed frame/message dataclasses
  hmac_auth.py      # HMAC-SHA256 helpers
  framing.py        # header pack/parse, canonical bytes, HMAC verification
  codec.py          # pure body serializer/deserializer
  transport.py      # exact socket reads and writes
  state_machine.py  # client/server legal frame transitions
  app.py            # small in-memory key-value application
  client.py         # synchronous client
  server.py         # thread-per-connection server
  inspect.py        # saved-frame inspection
  hexdump.py        # raw frame rendering
  cli.py            # argparse CLI
  errors.py         # stable protocol errors
```

---

## Wire Header

Header format:

```python
HEADER_FORMAT = "!4sBBHQI32s"
```

Fields:

| Field | Size | Meaning |
|---|---:|---|
| `MAGIC` | 4 bytes | ASCII `TP01` |
| `VERSION` | 1 byte | Protocol version |
| `TYPE` | 1 byte | Message opcode |
| `FLAGS` | 2 bytes | Currently must be zero |
| `REQUEST_ID` | 8 bytes | Control ID `0` or app request ID |
| `BODY_LEN` | 4 bytes | Exact body byte length |
| `HMAC_TAG` | 32 bytes | HMAC-SHA256 tag |

Total:

```text
52 bytes
```

---

## Message Types

| Opcode | Name | Purpose |
|---:|---|---|
| `0x01` | `HELLO` | Client version advertisement |
| `0x02` | `HELLO_ACK` | Server selected version |
| `0x03` | `PING` | Control ping |
| `0x04` | `PONG` | Control pong |
| `0x05` | `REQUEST` | Application request |
| `0x06` | `RESPONSE` | Application response |
| `0x07` | `ERROR` | Protocol/application error |
| `0x08` | `BYE` | Graceful close |

---

## Commands

| Opcode | Command | Request Args | Response Values |
|---:|---|---|---|
| `0x01` | `ECHO` | text | text |
| `0x02` | `TIME` | none | UTC ISO timestamp |
| `0x03` | `KV_PUT` | key, value | `stored` |
| `0x04` | `KV_GET` | key | value |
| `0x05` | `KV_DELETE` | key | `deleted` / `not found` |

---

## Error Codes

Wire error codes include:
- `BAD_MAGIC`
- `UNSUPPORTED_VERSION`
- `BAD_HMAC`
- `FRAME_TOO_LARGE`
- `MALFORMED_BODY`
- `BAD_STATE`
- `UNKNOWN_MESSAGE_TYPE`
- `UNKNOWN_COMMAND`
- `TIMEOUT`
- `INTERNAL_ERROR`
- `ILLEGAL_FLAGS`
- `NOT_FOUND`
- `TRUNCATED_FRAME`
- `STORE_FULL`

Fatal errors close the connection. Application errors such as `NOT_FOUND` and `STORE_FULL` can be returned as `ERROR` frames without closing the connection.

---

## Framing Design

### Encode

```text
encode_frame(key, message_type, request_id, body)
  ├── reject body over max_frame_size
  ├── reject unsupported flags
  ├── build canonical header with zero HMAC slot
  ├── compute HMAC-SHA256 over canonical header + body
  ├── pack final header with tag
  └── return header + body
```

### Parse

```text
parse_header(header)
  ├── require exactly 52 bytes
  ├── unpack network-order fields
  ├── verify magic
  ├── verify supported version
  ├── convert opcode to MessageType
  ├── reject illegal flags
  ├── reject body_len > max_frame_size
  └── return header Frame + body_len
```

### Verify

```text
verify_frame(key, header_frame, body)
  ├── rebuild canonical header/body bytes
  ├── compare HMAC with hmac.compare_digest
  └── return Frame with body
```

---

## Codec Design

The codec maps typed message dataclasses to deterministic body bytes.

Primitive encodings:
- `u8`
- `u16`
- `u64`
- UTF-8 string prefixed by `u16` byte length

Codec rules:
- strings must encode/decode as UTF-8
- strings cannot exceed 65,535 encoded bytes
- command and error values must be known enums
- request/response arity must match command schema
- no trailing bytes allowed
- decode errors become protocol errors, not crashes

---

## Transport Design

### `read_exact()`

Reads exactly `N` bytes or raises:
- `ConnectionClosed`
- `TransportTimeout`

Behavior:
- loops until requested byte count arrives
- handles EOF before or during a read
- supports per-read timeout
- supports total frame deadline

### `read_frame()`

```text
read_frame(sock, key)
  ├── read first header byte under idle timeout
  ├── start total frame deadline
  ├── read remaining header bytes
  ├── parse header
  ├── read declared body length
  ├── optionally call raw-frame hook
  └── verify HMAC
```

### `write_frame()`

Uses `sock.sendall()` and converts socket failures to ToyProto transport errors.

---

## State Machine

### States

- `NEW`
- `HANDSHAKING`
- `READY`
- `CLOSING`
- `CLOSED`

### Client send/receive contract

Client sends:
- `HELLO` in `NEW`
- `PING` / `REQUEST` in `READY`
- `BYE` in `READY` or `CLOSING`

Client receives:
- `HELLO_ACK` in `HANDSHAKING`
- `ERROR` in `HANDSHAKING` or `READY`
- `PONG` / `RESPONSE` in `READY`
- `BYE` in `READY` or `CLOSING`

### Server send/receive contract

Server receives:
- `HELLO` in `NEW`
- `PING` / `REQUEST` in `READY`
- `BYE` in `READY` or `CLOSING`

Server sends:
- `HELLO_ACK` in `HANDSHAKING`
- `ERROR` in early/handshake/ready states
- `PONG` / `RESPONSE` in `READY`
- `BYE` in `READY` or `CLOSING`

---

## Client Design

`ToyProtoClient` is synchronous and single-use after close or fatal failure.

Connection flow:

```text
connect()
  ├── create TCP connection
  ├── set TCP_NODELAY
  ├── send HELLO with supported versions
  ├── read HELLO_ACK control frame
  ├── verify selected version
  └── state READY
```

Request flow:

```text
request(command, args)
  ├── generate nonzero request ID
  ├── send REQUEST
  ├── read RESPONSE
  ├── require matching request ID
  ├── require matching command
  └── return Response
```

Ping flow:

```text
ping(nonce)
  ├── send PING with request_id 0
  ├── read PONG
  ├── require same nonce
  └── return nonce
```

Close flow:
- send best-effort `BYE`
- swallow peer-already-gone errors
- close socket
- mark state closed

---

## Server Design

`ToyProtoServer` is a bounded thread-per-connection TCP server.

Accept loop:

```text
serve_forever()
  ├── create AF_INET/SOCK_STREAM listener
  ├── SO_REUSEADDR
  ├── bind/listen
  ├── accept with short timeout
  ├── set TCP_NODELAY on connection
  ├── acquire bounded connection slot
  ├── close immediately if at capacity
  └── start daemon handler thread
```

Connection handler:

```text
_handle_connection()
  ├── create server state machine
  ├── read frames until stop/closed
  ├── verify HMAC and decode message
  ├── enforce state transition
  ├── dispatch HELLO/PING/REQUEST/BYE
  ├── send responses/errors
  ├── close on fatal parse/auth errors
  ├── count nonfatal malformed frames
  └── log per-connection stats on close
```

Resource limits:
- connection cap
- max frame size
- per-read timeouts
- idle timeout
- total frame assembly deadline
- malformed-frame budget
- max key-value keys

---

## Application Design

`ToyApplication` owns a process-local dictionary guarded by a lock.

Commands:
- `ECHO` returns the input string
- `TIME` returns UTC ISO timestamp
- `KV_PUT` inserts/replaces a value, enforcing max key count
- `KV_GET` returns a value or `NOT_FOUND`
- `KV_DELETE` removes a key and returns whether it existed

The app is intentionally small because the protocol is the capstone, not the database.

---

## Inspection Tools

### `inspect_bytes()`

Returns a dictionary without raising:
- byte size
- raw header fields
- body hex
- structural `valid` boolean
- separate `hmac_valid` verdict
- decoded body when possible
- error message when malformed

Important distinction:
- `valid` means structurally parseable and decodable
- `hmac_valid` is authentication status when a key is supplied

### `inspect_file()`

Reads at most one frame plus one byte and rejects larger files instead of loading hostile input into memory.

### `describe_raw_frame()`

Renders raw frame metadata and a hex dump.

---

## CLI Surface

Commands:
- `toyproto server`
- `toyproto client`
- `toyproto ping`
- `toyproto echo`
- `toyproto time`
- `toyproto put`
- `toyproto get`
- `toyproto delete`
- `toyproto inspect`
- `toyproto hexdump`

Key sources:
- `TOYPROTO_KEY`
- `--key`
- `--key-file`

Keys are treated as UTF-8 text and stripped of surrounding whitespace.

---

## Known Limits

- One protocol version.
- Pre-shared key only.
- No encryption.
- No replay protection.
- No production identity model.
- No persistence.
- IPv4 only.
- Synchronous request/response.
- No multiplexing.
- Thread-per-connection server.
- No HTTP/web layer.
- Server closes excess TCP connections with no protocol response.

---

## Verification Summary

The repository configures:
- Python 3.11+
- zero runtime dependencies
- pytest
- pytest-cov
- strict mypy
- ruff
- coverage fail-under 95
- CI on Python 3.11, 3.12, and 3.13
- generated binary frame fixtures before CI tests

README states:
- 221 tests
- approximately 99% current coverage
- offline and loopback tests
- committed and regenerable malformed frame fixtures

---

*Constitution reference: Article 4 (engineering quality), Article 6 (behavior verification), Article 7 (progressive complexity), and Article 8 (valid learner work).*

---


# Interface Design Specification
## App — Network Protocol
**Binary Protocol Systems Group | Document 3 of 5**

---

## Public CLI Interface

### Version

```powershell
toyproto --version
```

---

## Server

```powershell
toyproto server --host 127.0.0.1 --port 9000
```

Common options:

```powershell
toyproto server --host 127.0.0.1 --port 9000 -v --hexdump
toyproto server --idle-timeout 3600
toyproto server --timeout 5
toyproto server --max-frame-size 1048576
toyproto server --max-frame-seconds 30
toyproto server --max-malformed-frames 1
toyproto server --max-connections 64
toyproto server --max-kv-keys 1024
```

Key options:
- `--key`
- `--key-file`
- `TOYPROTO_KEY`

---

## Interactive Client

```powershell
toyproto client --host 127.0.0.1 --port 9000
```

Interactive commands:

```text
ping
echo TEXT
time
put KEY VALUE
get KEY
delete KEY
quit
```

---

## One-Shot Client Commands

### Ping

```powershell
toyproto ping --port 9000
```

Output:

```text
PONG <nonce>
```

### Echo

```powershell
toyproto echo "hello" --port 9000
```

### Time

```powershell
toyproto time --port 9000
```

### Put

```powershell
toyproto put color blue --port 9000
```

### Get

```powershell
toyproto get color --port 9000
```

### Delete

```powershell
toyproto delete color --port 9000
```

---

## Inspector Commands

### Inspect

```powershell
toyproto inspect tests\fixtures\frames\valid_hello.bin --key fixture-test-key
```

Returns JSON with fields such as:
- `size`
- `valid`
- `hmac_valid`
- `magic`
- `version`
- `message_type_raw`
- `message_type`
- `request_id`
- `body_length`
- `actual_body_length`
- `decoded_body`
- `error`

Exit behavior:
- exits `0` when `valid` is true
- exits `2` when `valid` is false

### Hexdump

```powershell
toyproto hexdump tests\fixtures\frames\valid_ping.bin
```

Shows:
- raw frame length
- decoded header fields
- body hex
- offset-based hex view

---

## Shared Connection Options

| Option | Applies To | Meaning |
|---|---|---|
| `--host` | client/server | Host, default `127.0.0.1` |
| `--port` | client/server | Port, default `9000` |
| `--key` | client/server/inspect | Shared key text |
| `--key-file` | client/server/inspect | File containing shared key |
| `--timeout` | client/server | Client connect/read timeout; server per-read timeout |
| `--max-frame-size` | client/server/inspect | Maximum body size |
| `--max-frame-seconds` | client/server | Total frame assembly budget |
| `--verbose` | client/server | Lifecycle and frame metadata logging |
| `--hexdump` | client/server | Print raw frames |

---

## Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `2` | Usage error or runtime/protocol error |
| `130` | Interrupted with Ctrl-C |

---

## Public Python API

Primary imports:

```python
from toyproto import PROTOCOL_VERSION, ToyProtoClient, ToyProtoServer
```

Lower-level imports:

```python
from toyproto.codec import encode_message, decode_message
from toyproto.framing import encode_frame, parse_header, parse_frame_bytes
from toyproto.transport import read_frame, write_frame, read_exact
from toyproto.types import Hello, Ping, Request, Response, ErrorMessage
from toyproto.constants import Command, MessageType, ErrorCode
```

---

## Frame Encoding Contract

```python
message_type, body = encode_message(Request(Command.ECHO, ("hello",)))
raw = encode_frame(key, message_type, request_id=1, body=body)
```

Requirements:
- non-empty key
- body length <= max frame size
- flags must be zero
- request ID must fit unsigned 64-bit header field

---

## Frame Decoding Contract

```python
frame = parse_frame_bytes(raw, key)
message = decode_message(frame.message_type, frame.body)
```

Failure modes:
- bad magic
- unsupported version
- unknown message type
- illegal flags
- oversized body length
- truncated header/body
- trailing bytes
- bad HMAC
- malformed body
- unknown command/error code
- invalid UTF-8

---

## Application Request Contract

### Request

```python
Request(Command.ECHO, ("hello",))
Request(Command.TIME, ())
Request(Command.KV_PUT, ("color", "blue"))
Request(Command.KV_GET, ("color",))
Request(Command.KV_DELETE, ("color",))
```

### Response

```python
Response(Command.ECHO, ("hello",))
Response(Command.TIME, ("2026-07-02T01:00:00Z",))
Response(Command.KV_PUT, ("stored",))
Response(Command.KV_GET, ("blue",))
Response(Command.KV_DELETE, ("deleted",))
```

---

## Side Effects

| Operation | Side Effect |
|---|---|
| server start | Opens TCP listener |
| client command | Opens TCP connection |
| handshake | Sends `HELLO` / `HELLO_ACK` frames |
| one-shot request | Sends request and closes connection |
| `put` | Mutates server in-memory dictionary |
| `delete` | Mutates server in-memory dictionary |
| server shutdown | Closes listener and active sockets |
| `inspect` | Reads one frame-sized file cap |
| `hexdump` | Reads one frame-sized file cap |
| `--hexdump` | Writes raw frame reports to stderr |
| `--verbose` | Writes lifecycle logs |

---

## Error Output Contract

CLI errors use `toyproto:` prefix where applicable:

```text
toyproto: provide --key, --key-file, or TOYPROTO_KEY
toyproto: address already in use (127.0.0.1:9000)
toyproto: BAD_HMAC: frame authentication failed
```

---

*Constitution reference: Article 4 (input/output boundaries), Article 6 (verification), and Article 8 (understandable and verifiable work).*

---


# Runbook
## App — Network Protocol
**Binary Protocol Systems Group | Document 4 of 5**

---

## Requirements

### Runtime

- Python 3.11+
- Local TCP networking
- No runtime dependencies

### Development

- pytest
- pytest-cov
- mypy
- ruff

---

## Installation

### Editable install with dev tools

```powershell
python -m pip install -e ".[dev]"
```

### Reproducible pinned dev toolchain

```powershell
python -m pip install -e . -r requirements-dev.txt
```

---

## First Smoke Test

### Terminal 1

```powershell
$env:TOYPROTO_KEY = "local-demo-secret"
toyproto server --host 127.0.0.1 --port 9000 -v
```

### Terminal 2

```powershell
$env:TOYPROTO_KEY = "local-demo-secret"
toyproto ping --port 9000
toyproto echo "hello" --port 9000
toyproto put color blue --port 9000
toyproto get color --port 9000
toyproto delete color --port 9000
toyproto get color --port 9000
```

Expected:
- ping returns `PONG`
- echo returns `hello`
- put returns `stored`
- first get returns `blue`
- delete returns `deleted`
- second get returns protocol/application error for missing key

---

## Interactive Client

Start server with longer idle timeout:

```powershell
toyproto server --port 9000 --idle-timeout 3600
```

Start client:

```powershell
toyproto client --port 9000 --hexdump
```

Try:

```text
ping
echo hello
time
put color blue
get color
delete color
quit
```

---

## Generate Frame Fixtures

```powershell
python scripts/generate_frame_fixtures.py
```

Expected fixture categories:
- valid frames
- bad magic
- bad HMAC
- oversized length
- truncated input
- bad UTF-8
- unknown opcode
- valid frame illegal before handshake

---

## Inspect Frames

```powershell
toyproto inspect tests\fixtures\frames\valid_hello.bin --key fixture-test-key
```

No-key structural inspection:

```powershell
toyproto inspect tests\fixtures\frames\valid_ping.bin
```

Expected:
- `valid` can be true without a key
- `hmac_valid` is `null` without a key
- with a key, HMAC failure returns `hmac_valid: false`

---

## Hexdump Frames

```powershell
toyproto hexdump tests\fixtures\frames\valid_ping.bin
```

Use this to show:
- header fields
- body length
- HMAC tag
- raw bytes

---

## Quality Checks

### Tests

```powershell
pytest
```

### Tests with explicit coverage gate

```powershell
pytest --cov=toyproto --cov-report=term-missing --cov-fail-under=95
```

### Type checking

```powershell
python -m mypy
```

### Lint

```powershell
ruff check src tests scripts
```

---

## CI Parity

CI runs:
- Ubuntu latest
- Python 3.11, 3.12, and 3.13
- editable install with pinned dev toolchain
- frame fixture generation
- ruff
- mypy strict
- pytest with 95% coverage floor

---

## Health Checks

### Import check

```powershell
python - <<'PY'
from toyproto import PROTOCOL_VERSION, ToyProtoClient, ToyProtoServer
print(PROTOCOL_VERSION, ToyProtoClient, ToyProtoServer)
PY
```

### Codec check

```powershell
python - <<'PY'
from toyproto.codec import encode_message, decode_message
from toyproto.constants import Command
from toyproto.types import Request
msg_type, body = encode_message(Request(Command.ECHO, ("hello",)))
print(msg_type.name, decode_message(msg_type, body))
PY
```

### Frame check

```powershell
python - <<'PY'
from toyproto.codec import encode_message
from toyproto.constants import Command
from toyproto.framing import encode_frame, parse_frame_bytes
from toyproto.types import Request
key = b"demo"
mt, body = encode_message(Request(Command.ECHO, ("hi",)))
raw = encode_frame(key, mt, 1, body)
print(parse_frame_bytes(raw, key))
PY
```

---

## Troubleshooting

### `provide --key, --key-file, or TOYPROTO_KEY`

Fix:

```powershell
$env:TOYPROTO_KEY = "local-demo-secret"
```

or:

```powershell
toyproto ping --key local-demo-secret
```

---

### Connection refused

Check:
- server is running
- host and port match
- firewall is not blocking loopback
- server did not exit after error

---

### Address already in use

Fix:
- stop the old server
- choose another port

```powershell
toyproto server --port 9001
```

---

### Bad HMAC

Cause:
- client and server keys differ
- key file has unexpected content
- captured frame was modified

Note:
- whitespace is stripped uniformly from key sources
- command-line keys may appear in process listings

---

### Unsupported version

Cause:
- frame version is not in supported versions
- test fixture intentionally uses invalid version

Expected:
- endpoint returns/closes with `UNSUPPORTED_VERSION`

---

### Frame too large

Cause:
- declared body exceeds max frame size

Fix:
- reduce payload
- raise `--max-frame-size` for local testing

---

### Interactive client disconnects while paused

Cause:
- server idle timeout defaults to 60 seconds

Fix:

```powershell
toyproto server --idle-timeout 3600
```

---

### Server closes excess connections without response

Expected:
- the server is at `--max-connections`
- capacity protection closes extra sockets immediately

Fix:
- lower client concurrency
- raise `--max-connections`

---

## Maintenance Notes

- Preserve the fixed-header protocol unless a protocol-version ADR is written.
- Keep codec pure and socket-free.
- Keep exact-read transport behavior.
- Add tests before changing header layout.
- Add tests before changing HMAC canonicalization.
- Add tests before changing state-machine rules.
- Keep HMAC limitations explicit.
- Do not claim encryption or replay protection.
- Keep limits documented as security controls.
- Preserve offline frame inspection tools.
- Preserve CI fixture generation and coverage gate.

---

*Constitution reference: Article 6 (behavior verification), Article 5 (constraints and trade-offs), and Article 8 (verifiable learner work).*

---


# Lessons Learned
## App — Network Protocol
**Binary Protocol Systems Group | Document 5 of 5**

---

## Why This Design Was Chosen

This design was chosen because a binary TCP protocol is one of the clearest ways to demonstrate networking fundamentals. TCP gives a byte stream, not messages. The application must decide where frames begin/end, how large they may be, how to authenticate them, how to reject malformed data, and what message order is legal.

The fixed 52-byte header made the protocol easy to inspect. Every field has a purpose and a predictable offset. The length-prefixed body made exact reads possible. HMAC over canonical bytes made authentication deterministic. State machines made legal ordering explicit.

The project also chose an intentionally small application layer. `ECHO`, `TIME`, and a bounded in-memory key-value store are enough to prove request/response behavior without turning the project into a database or web server.

---

## What Was Intentionally Omitted

**TLS/encryption:** Out of scope. HMAC authenticates bytes but does not hide them.

**Replay protection:** Out of scope. Captured valid frames can be replayed.

**Public-key identity:** Out of scope. Anyone with the shared key can forge frames.

**Persistence:** Out of scope. The key-value store is memory-only.

**HTTP/web layer:** Out of scope because the project is about binary protocol design.

**Async server:** Deferred. Thread-per-connection is enough for this lab.

**Multiplexing:** Deferred. The protocol is synchronous request/response.

**IPv6:** Deferred. The server uses IPv4 `AF_INET`.

---

## Biggest Weakness

The biggest weakness is the security model. HMAC protects integrity and shared-key authenticity, but it does not encrypt traffic, identify a user, rotate keys, or prevent replay. This is acceptable for an academic protocol capstone, but it must not be described as production-secure.

The second weakness is scalability. A thread-per-connection server with an in-memory store is simple and reviewable, but it is not a high-concurrency production architecture.

The third weakness is protocol evolution. There is version negotiation, but only one version exists today. Future changes need careful compatibility rules.

---

## Scaling Considerations

**If security grows:**
- run under TLS
- add replay windows/nonces
- add key IDs and key rotation
- separate authentication identity from shared secret possession
- avoid command-line secrets

**If concurrency grows:**
- move to asyncio or selectors
- add backpressure metrics
- add per-IP connection limits
- add bounded worker pools

**If protocol evolves:**
- reserve extension fields
- define version downgrade behavior
- add compatibility tests for old fixtures
- document every header/body change

**If application grows:**
- replace in-memory store with persistence
- add request authorization
- add structured application errors
- keep protocol layer independent from app logic

---

## What the Next Refactor Would Be

1. **Replay defense** — add monotonically increasing nonces or a bounded replay cache.

2. **Protocol version 2 draft** — define a backward-compatible extension story.

3. **Async server prototype** — compare selector/asyncio behavior to thread-per-connection.

4. **Structured metrics** — export frame counts, error codes, timeouts, and capacity refusals.

5. **Key ID support** — allow multiple accepted shared keys during rotation.

---

## What This Project Taught

- **TCP is not message-oriented.** Framing is an application responsibility.

- **Binary protocols need exact validation.** Every byte offset, length, enum, and trailing byte matters.

- **Authentication bytes must be canonical.** Both sides must agree exactly which bytes are signed.

- **HMAC is not encryption.** Integrity and confidentiality are separate properties.

- **State machines are protocol architecture.** A frame can be valid bytes and still illegal in the current phase.

- **Timeouts need layers.** Per-read timeouts are not enough against slow-dribble peers.

- **Diagnostics matter.** Inspectors and hexdumps make binary systems reviewable.

- **Scope discipline makes the project stronger.** ToyProto is a clear binary protocol lab, not a vague attempt at TLS, HTTP, or a production messaging system.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity) for Network Protocol.*
