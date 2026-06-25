# Changelog

All notable changes to ToyProto Lab are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No unreleased changes._

## [1.0.0] - 2026-06-17

Initial release.

### Added
- Framed binary protocol over raw TCP: a 52-byte fixed header (magic, version,
  type, flags, request id, body length, HMAC-SHA256 tag), network byte order
  throughout.
- A pure, defensive binary codec for every message type, proven with exhaustive
  malformed-input and fuzz tests.
- HMAC-SHA256 frame authentication over a zeroed-tag canonical input, verified
  with `hmac.compare_digest`.
- Robust frame reader: exact reads, split/merged-frame handling, oversized-length
  rejection before allocation, and a total per-frame read deadline (slow-read
  defense).
- Client and server connection state machines with a HELLO/HELLO_ACK handshake
  and version negotiation.
- CLI client and server, plus `inspect` and `hexdump` frame tools and `--version`.
- Connection safety limits: max frame size, per-read and idle timeouts, a
  malformed-frame budget, a concurrent-connection cap, and a bounded in-memory
  key-value store.
- Error codes `TRUNCATED_FRAME` (fatal framing failures) and `STORE_FULL`
  (nonfatal key-value capacity).
- Documentation: protocol specification, architecture decision records, and
  reproducible binary frame fixtures.
- Quality gates wired into CI: `ruff`, `mypy --strict`, and `pytest` with an
  enforced coverage floor.
- PEP 561 marker (`py.typed`) and automatic fixture generation before tests when
  fixtures are missing.

### Changed
- Server constructor parameter `timeout` renamed to `idle_timeout` (`timeout`
  remains a deprecated alias).
- Client stores and uses the negotiated protocol version after handshake.
- Interactive client banner documents the server idle-timeout requirement.
