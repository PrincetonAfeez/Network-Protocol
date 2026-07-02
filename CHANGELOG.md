# Changelog

All notable changes to ToyProto Lab are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- CLI exit codes: usage/configuration errors exit `2`; runtime/protocol/network
  errors exit `3` (Ctrl-C remains `130`).

## [1.0.3] - 2026-06-17

### Added
- Comprehensive unit tests across all modules: client, server, codec, transport,
  framing, errors, types, hexdump, constants, inspect, and CLI entry points.
- Integration coverage for malformed server control frames and client handshake
  failure modes.
- 221 tests with ~99% line coverage across `src/toyproto/`.

### Changed
- CI and local `pytest` enforce a 95% coverage floor (raised from 85%).
- `pyproject.toml` dev dependency ranges and default pytest options aligned with
  the pinned lockfile and expanded suite.
- README reviewer instructions updated for the current quality gate.

### Fixed
- `.gitignore` excludes local network-protocol scope documents
  (`network_protocol_scope.txt`, `revised_network_protocol_scope.txt`).

## [1.0.2] - 2026-06-17

### Added
- CLI validation for `--max-frame-size`, `--idle-timeout`, `--max-connections`,
  `--max-kv-keys`, and `--max-malformed-frames`.
- Integration tests for client transport timeout invalidation, handshake failure,
  and malformed ping/response handling.
- Unit tests for HMAC edge cases and encode-side frame limits.

### Changed
- Server CLI no longer silently clamps `--idle-timeout` to 0.1 seconds; invalid
  values are rejected up front.
- Bind failures report a clear “address already in use” message.

### Fixed
- README contact guidance no longer references a removed placeholder email.

## [1.0.1] - 2026-06-17

### Added
- Server tracks negotiated wire version per connection; CLI `--max-kv-keys`,
  `--max-frame-seconds`, and client `--max-frame-seconds`.
- `APPLICATION_ERROR_CODES` for interactive client UX.
- Integration tests for shared KV, fatal close-without-ERROR, CLI one-shots,
  connection-cap refusal, wire version, client invalidation, and TCP retry.

### Changed
- Interactive client exits on connection-level errors; continues on `NOT_FOUND`
  and `STORE_FULL`.
- Client invalidates the session on `ConnectionClosed`, timeouts, and
  non-application `ProtocolError`s (single-use semantics).
- `connect()` raises when already connected; `max_frame_seconds` must be positive.
- `inspect` sets `hmac_valid=false` whenever a key is supplied but auth cannot
  succeed (including file I/O failures).
- Encode-side header struct errors use `TRUNCATED_FRAME`; handshake version
  mismatch sends authenticated ERROR then closes.
- PROTOCOL_SPEC §5 documents authenticated handshake errors and v1 header rules.

### Fixed
- Client zombie state after peer disconnect without explicit `close()`.
- README reviewer instructions no longer assume an unpublished GitHub remote.
- Removed placeholder author email from package metadata.

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
