# ToyProto Protocol Specification, Version 1

Status: implemented. All multi-byte integers use network byte order
(big-endian). A conforming implementation treats all received bytes as
untrusted.

## 1. Transport and framing

ToyProto runs over one TCP connection. TCP supplies an ordered byte stream, not
application messages. Readers MUST collect exactly 52 header bytes, validate
the header, reject an excessive body length, collect exactly `BODY_LEN` body
bytes, then authenticate the frame.

| Offset | Size | Field | Encoding |
|---:|---:|---|---|
| 0 | 4 | `MAGIC` | ASCII `TP01` |
| 4 | 1 | `VERSION` | uint8; currently 1 |
| 5 | 1 | `TYPE` | uint8 opcode |
| 6 | 2 | `FLAGS` | uint16; MUST be zero |
| 8 | 8 | `REQUEST_ID` | uint64 |
| 16 | 4 | `BODY_LEN` | uint32 |
| 20 | 32 | `HMAC_TAG` | HMAC-SHA256 |

The Python struct format is `!4sBBHQI32s`, exactly 52 bytes. The maximum body
length defaults to 1,048,576 bytes. A larger declared length is rejected before
body allocation or body reads.

No bytes may occur between frames. A saved single-frame artifact with bytes
after its declared body is malformed. Zero-length bodies are legal at the
framing layer, though version 1 message schemas all require fields.

## 2. Authentication

The shared secret is external configuration. The canonical HMAC input is:

```text
MAGIC || VERSION || TYPE || FLAGS || REQUEST_ID || BODY_LEN ||
32 zero bytes || BODY
```

The algorithm is HMAC-SHA256 and the tag is 32 bytes. Receivers recompute the
tag and compare with a constant-time comparison. HMAC authenticates bytes and
detects modification; it does not encrypt them or prevent replay.

## 3. Primitive body encodings

- `uint8`, `uint16`, and `uint64`: unsigned big-endian integers.
- `string`: uint16 byte length followed by strict UTF-8 bytes.
- Lists: an explicit uint8 count followed by schema-defined elements.
- No body may contain undeclared trailing bytes.

Truncation, invalid UTF-8, overrunning lengths, bad enum values, wrong field
counts, and trailing bytes are malformed.

## 4. Message opcodes and schemas

| Opcode | Name | Body |
|---:|---|---|
| `01` | `HELLO` | uint8 count, then count uint8 versions |
| `02` | `HELLO_ACK` | uint8 selected version |
| `03` | `PING` | uint64 nonce |
| `04` | `PONG` | uint64 echoed nonce |
| `05` | `REQUEST` | uint8 command, uint8 arg count, strings |
| `06` | `RESPONSE` | uint8 command, uint8 value count, strings |
| `07` | `ERROR` | uint16 error code, string reason |
| `08` | `BYE` | string reason |

Control messages (`HELLO`, `HELLO_ACK`, `PING`, `PONG`, `BYE`) use request ID
0. `REQUEST` and its matching `RESPONSE` use a nonzero ID; the response MUST
echo the request ID. An `ERROR` returned in response to a `REQUEST` echoes that
request's ID so the client can correlate it to the failed call; an `ERROR`
raised in a handshake or other control context uses request ID 0.

### Commands

| Command | Opcode | Request arguments | Response values |
|---|---:|---:|---:|
| `ECHO` | `01` | text | echoed text |
| `TIME` | `02` | none | UTC ISO-8601 timestamp |
| `KV_PUT` | `03` | key, value | `stored` |
| `KV_GET` | `04` | key | value |
| `KV_DELETE` | `05` | key | `deleted` or `not found` |

Every response has exactly one string value. The store is process-local memory.
`KV_GET` for an absent key returns `ERROR(NOT_FOUND)` rather than a response
value; `KV_DELETE` is idempotent and answers with `deleted` or `not found` as a
normal `RESPONSE`.

The store holds at most 1,024 distinct keys by default (`MAX_KV_KEYS`). Inserting
a new key when the store is full returns `ERROR(STORE_FULL)` without closing the
connection. Updating an existing key remains allowed at capacity.

## 5. Version negotiation

The client emits a version-1 frame containing `HELLO` and its supported version
list. The server chooses the highest mutually supported version and returns
`HELLO_ACK`. No overlap produces `UNSUPPORTED_VERSION` and closure. A frame
whose header version cannot itself be parsed by this implementation is rejected
immediately.

## 6. State machines

| Endpoint/state | Allowed incoming | Transition/behavior |
|---|---|---|
| Server `NEW` | `HELLO` | `HANDSHAKING` |
| Server `HANDSHAKING` | none | sends ACK -> `READY`, or ERROR -> close |
| Server `READY` | `PING`, `REQUEST`, `BYE` | respond; BYE -> `CLOSING` |
| Client `NEW` | none | sends HELLO -> `HANDSHAKING` |
| Client `HANDSHAKING` | `HELLO_ACK`, `ERROR` | ACK -> `READY`; ERROR -> close |
| Client `READY` | `PONG`, `RESPONSE`, `ERROR`, `BYE` | correlate/handle |
| Either `CLOSING` | `BYE` or EOF | `CLOSED` |
| Either `CLOSED` | none | all messages invalid |

Wrong-state messages produce `BAD_STATE` when an authenticated error can be
returned, then the server closes that connection. BYE is acknowledged with BYE.
EOF, timeout, fatal protocol error, and process shutdown also close sockets.

## 7. Error codes

| Value | Name | Default severity |
|---:|---|---|
| `0001` | `BAD_MAGIC` | fatal |
| `0002` | `UNSUPPORTED_VERSION` | fatal |
| `0003` | `BAD_HMAC` | fatal |
| `0004` | `FRAME_TOO_LARGE` | fatal |
| `0005` | `MALFORMED_BODY` | nonfatal at codec level |
| `0006` | `BAD_STATE` | nonfatal at protocol level |
| `0007` | `UNKNOWN_MESSAGE_TYPE` | fatal |
| `0008` | `UNKNOWN_COMMAND` | nonfatal |
| `0009` | `TIMEOUT` | fatal |
| `000A` | `INTERNAL_ERROR` | implementation-defined |
| `000B` | `ILLEGAL_FLAGS` | fatal |
| `000C` | `NOT_FOUND` | nonfatal |
| `000D` | `TRUNCATED_FRAME` | fatal |
| `000E` | `STORE_FULL` | nonfatal |

Bad magic, authentication, version, opcode, flags, length, truncation, and
timeout failures close immediately without a reply, because frame authenticity is
unknown or the frame is incomplete. Such fatal errors are not counted toward
`max_malformed_frames`. Nonfatal connection-level errors (malformed body, wrong
state) are answered with an `ERROR` and counted; the connection closes once
they reach `max_malformed_frames` (default 1). Request-level application errors
raised while *executing* a valid, decodable `REQUEST` (for example `NOT_FOUND`
for a missing key or `STORE_FULL` when the key-value cap is reached) are returned
as `ERROR` frames, are not counted, and do not close the connection. An unknown
command *opcode* is different: it is rejected during decoding as a malformed
body, so `UNKNOWN_COMMAND` is a counted connection-level error that closes the
connection like any other malformed input.

`INTERNAL_ERROR` is reserved for unexpected implementation failures. The server
sends an `ERROR(INTERNAL_ERROR)` frame when possible, then closes the
connection. It is not counted toward `max_malformed_frames`.

## 8. Timeouts and limits

Defaults are a 1 MiB body, five-second header read, five-second body read, and
a 60-second server idle policy. The idle timeout bounds the wait for the first
byte of each new frame; the header/body read timeouts bound the wait for the
rest of a frame already in flight. A separate total per-frame read deadline (30
seconds) bounds the *aggregate* time to assemble one frame, so a peer dribbling
bytes just under the per-read timeout is still dropped rather than holding a
thread open indefinitely. The server also caps concurrent connections (default
64); connections beyond the cap are refused immediately. The CLI exposes
`--timeout` for the read timeouts and `--idle-timeout` for the idle policy. When
using the interactive client, raise `--idle-timeout` on the server if the user may
pause at the prompt longer than the default idle window. EOF in
the middle of either region is a clean connection failure. Limits are
configurable for tests. The implementation handles split headers, split bodies, adjacent
frames, and zero body lengths without using TCP receive boundaries as frame
boundaries.

