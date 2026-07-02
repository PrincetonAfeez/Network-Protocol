# ToyProto Lab

Academic capstone project — framed binary protocol over TCP (author: Princ;
add a contact line here before submission if your course requires one).

ToyProto is a CLI-first, framed binary application protocol built directly on
TCP. It is deliberately small enough to audit byte by byte and hostile enough
in its assumptions to demonstrate defensive systems programming.

It includes a precise 52-byte header, length-prefixed frames, a pure binary
codec, HMAC-SHA256 authentication, version negotiation, client/server state
machines, exact socket reads, an in-memory key-value app, frame inspection,
reproducible malformed fixtures, and offline plus loopback tests.

## For reviewers

From a local checkout, install and run the full quality gate:

```powershell
python -m pip install -e . -r requirements-dev.txt
pytest
python -m mypy
ruff check src tests scripts
```

The test suite has **221 tests** and enforces **95% line coverage** on
`src/toyproto/` (~99% at present). Coverage and reporting are configured in
`pyproject.toml`; CI runs the same gate on Python 3.11–3.13.

CI is defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). After
publishing to GitHub, add your remote and optionally embed a CI badge:
`https://github.com/<user>/toyproto-lab/actions/workflows/ci.yml/badge.svg`

Binary frame fixtures under `tests/fixtures/frames/` are committed to the
repository. If they are missing, `pytest` generates them automatically via
`scripts/generate_frame_fixtures.py` before tests run.

## Quick start

Python 3.11 or newer is required.

```powershell
python -m pip install -e ".[dev]"
$env:TOYPROTO_KEY = "local-demo-secret"
toyproto server --host 127.0.0.1 --port 9000 -v
```

In another terminal:

```powershell
$env:TOYPROTO_KEY = "local-demo-secret"
toyproto ping --port 9000
toyproto echo "hello" --port 9000
toyproto put color blue --port 9000
toyproto get color --port 9000
toyproto client --port 9000 --hexdump
```

When using the interactive client, raise the server idle timeout if you may
pause at the prompt for more than 60 seconds (the default), for example
`toyproto server --idle-timeout 3600`. On the client, a single `--timeout`
value applies to TCP connect and to idle, header, and body read waits; the
server separates `--timeout` (per-read) from `--idle-timeout` (between frames).
Client commands also accept `--max-frame-seconds` (default 30) as the total
budget to assemble one inbound frame.

Each one-shot command creates a new connection. Because the key-value store is
in memory on the server, values persist across those connections until the
server exits.

Run the full quality gate (tests, types, lint):

```powershell
pytest                          # 221 tests; 95% coverage floor on toyproto
python -m mypy                  # strict type checking, zero issues
ruff check src tests scripts    # lint
```

For a byte-for-byte reproducible toolchain (the versions CI runs), install the
pinned lockfile instead of the declared ranges:

```powershell
python -m pip install -e . -r requirements-dev.txt
```

Generate or refresh the educational binary fixtures and try the inspector:

```powershell
python scripts/generate_frame_fixtures.py
toyproto inspect tests/fixtures/frames/valid_hello.bin --key fixture-test-key
toyproto hexdump tests/fixtures/frames/valid_ping.bin
```

Fixtures are also checked in under `tests/fixtures/frames/` and regenerated
automatically when missing before `pytest` runs.

The key may come from `TOYPROTO_KEY`, `--key`, or an ignored `--key-file`.
Keys are treated as UTF-8 text and surrounding whitespace is stripped from every
source uniformly, so the same secret matches however it is supplied (for example
a key file written with a trailing newline). Command-line keys are convenient for
a local demo but can appear in process listings.

## Architecture

The package keeps responsibilities narrow:

```text
CLI -> client/server protocol -> state machine + app
                         |
                    pure codec
                         |
                 framing + HMAC
                         |
                exact-read transport
                         |
                       TCP
```

TCP is an ordered byte stream, not a message transport. One `recv()` can return
part of a header, part of a body, or bytes from several frames. `read_exact`
therefore loops until the requested byte count arrives, EOF occurs, or a
timeout fires. The reader validates the header and rejects an oversized
`BODY_LEN` before reading or allocating the body. Both endpoints set
`TCP_NODELAY` so each small control frame is sent immediately rather than being
coalesced by Nagle's algorithm.

The message type byte is an opcode. The codec is a binary serializer with the
same discipline as bytecode decoding: explicit schemas, bounded lengths,
strict UTF-8, known enum values, and no trailing bytes. It is pure and performs
no socket, environment, or application work.

## Security model

Every frame has an HMAC-SHA256 tag. The authenticated bytes are the complete
header with its 32-byte tag slot zeroed, followed by the exact body. Verification
uses `hmac.compare_digest`.

HMAC provides integrity and shared-key authenticity. It does **not** provide
confidentiality: ToyProto traffic is not encrypted. The project is not TLS, a
production identity system, or replay-proof. Anyone with the shared key can
forge frames, and captured valid frames can be replayed.

Limits are security controls, not decoration: the default body cap is 1 MiB,
header/body reads default to five seconds, a total per-frame read deadline (30
seconds) drops slow-dribble peers, idle connections close after 60 seconds,
concurrent connections are capped (default 64), the in-memory key-value store is
bounded, illegal flags are rejected, fatal parse/authentication errors close the
connection, and request IDs are checked.

## Tools

`--verbose` logs lifecycle and frame metadata without logging the secret.
`--hexdump` prints raw bytes plus decoded header fields. `toyproto inspect`
parses saved frames, optionally verifies HMAC, decodes valid bodies, and reports
malformed input without crashing. In its report, `valid` means the frame is
structurally parseable and decodable, while `hmac_valid` is the separate
authenticity verdict (`null` when no key is supplied), so a frame can be `valid`
yet unauthenticated.

The generated fixtures include valid frames plus bad magic, bad HMAC,
oversized length, truncated input, bad UTF-8, unknown opcode, and a valid frame
that is illegal before the handshake.

## Exit codes

The CLI uses conventional process exit codes (also shown in `toyproto --help`):

| Code | Meaning |
|---:|---|
| `0` | success (`inspect` exits `0` when the frame is structurally valid and decodable) |
| `2` | usage error (bad arguments) or a runtime/protocol error (connection refused, bad HMAC, timeout, unsupported version, malformed response; `inspect` when `valid` is false) |
| `130` | interrupted with Ctrl-C |

For `toyproto inspect`, `valid` means the frame is structurally parseable and
decodable; it is not an authenticity verdict. Without a key, a structurally
valid frame exits `0` while `hmac_valid` is `null`. With a key, any
authentication failure (including truncation before verify) sets `hmac_valid` to
`false` and the command exits `2`.

## Documentation

- [Protocol specification](docs/PROTOCOL_SPEC.md)
- [Architecture decisions](docs/ADRS.md)
- [Changelog](CHANGELOG.md)

## Known limitations and non-goals

ToyProto has one protocol version, a pre-shared key, synchronous request/
response behavior, no encryption, no replay protection, no persistence, IPv4
only (`AF_INET`), and a simple thread-per-connection server. When the server
reaches its connection cap it closes excess TCP connections immediately with no
protocol response. There is no HTTP or web layer because the core learning
objective is binary protocol design, not presentation.
