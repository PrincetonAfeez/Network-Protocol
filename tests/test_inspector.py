from __future__ import annotations

from pathlib import Path

from toyproto.hexdump import describe_raw_frame
from toyproto.inspect import inspect_bytes, inspect_file

FIXTURES = Path(__file__).parent / "fixtures" / "frames"
KEY = b"fixture-test-key"


def test_valid_fixture_decodes() -> None:
    report = inspect_file(FIXTURES / "valid_hello.bin", key=KEY)
    assert report["valid"] is True
    assert report["hmac_valid"] is True
    assert report["message_type"] == "HELLO"


def test_invalid_fixture_reports_error_without_crashing() -> None:
    for path in FIXTURES.glob("*.bin"):
        report = inspect_file(path, key=KEY)
        assert isinstance(report, dict)
        if path.name.startswith(("bad_", "truncated_", "oversized_", "unknown_")):
            assert report["valid"] is False
            assert "error" in report


def test_arbitrary_bytes_report_error() -> None:
    report = inspect_bytes(b"\x00\x01")
    assert report["valid"] is False
    assert "error" in report


def test_describe_raw_frame_breaks_out_header_fields() -> None:
    text = describe_raw_frame((FIXTURES / "valid_ping.bin").read_bytes())
    for field in ("magic:", "version:", "type:", "flags:", "request_id:", "body_len:", "hmac:"):
        assert field in text
    assert "TP01" in text


def test_describe_raw_frame_handles_truncated_input() -> None:
    text = describe_raw_frame(b"\x00\x01\x02")
    assert "truncated header" in text


def test_inspect_without_key_reports_structural_validity_only() -> None:
    report = inspect_bytes((FIXTURES / "valid_hello.bin").read_bytes())
    assert report["valid"] is True       # structurally parseable and decodable
    assert report["hmac_valid"] is None  # authenticity unverified without a key


def test_inspect_file_refuses_oversized_file(tmp_path) -> None:
    # cap = HEADER_SIZE + max_frame_size; with max_frame_size=10 the cap is 62,
    # so a 200-byte file is refused rather than loaded.
    big = tmp_path / "huge.bin"
    big.write_bytes(b"\x00" * 200)
    report = inspect_file(big, max_frame_size=10)
    assert report["valid"] is False
    assert "larger than a single frame" in report["error"]

