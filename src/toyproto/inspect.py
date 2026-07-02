"""Safe, educational inspection of saved frame bytes."""
 
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from .codec import decode_message
from .constants import HEADER_SIZE, HEADER_STRUCT, MAX_FRAME_SIZE
from .errors import ProtocolError
from .framing import parse_frame_bytes, parse_header


def _message_to_dict(message: object) -> dict[str, Any]:
    if not is_dataclass(message):
        return {"value": repr(message)}
    result = asdict(cast(Any, message))
    for key, value in tuple(result.items()):
        if hasattr(value, "name"):
            result[key] = value.name
    return {"class": type(message).__name__, **result}


def inspect_bytes(
    data: bytes,
    *,
    key: bytes | None = None,
    max_frame_size: int = MAX_FRAME_SIZE,
) -> dict[str, Any]:
    """Decode and report on saved frame bytes without ever raising.

    ``valid`` reports whether the frame is structurally parseable and its body
    decodes; it is *not* an authenticity verdict. Authenticity is reported
    separately in ``hmac_valid``: ``True``/``False`` when a key is supplied and
    the tag is checked, or ``None`` when no key is given (unverified). A frame
    can therefore be ``valid`` while ``hmac_valid`` is ``None`` or ``False``.
    """
    report: dict[str, Any] = {
        "size": len(data),
        "valid": False,
        "hmac_valid": None,
    }
    if len(data) < HEADER_SIZE:
        report["error"] = f"truncated header: {len(data)}/{HEADER_SIZE} bytes"
        report["raw_hex"] = data.hex()
        if key is not None:
            report["hmac_valid"] = False
        return report
    magic, version, raw_type, flags, request_id, body_len, tag = HEADER_STRUCT.unpack(
        data[:HEADER_SIZE]
    )
    report.update(
        {
            "magic": magic.decode("ascii", errors="replace"),
            "version": version,
            "message_type_raw": raw_type,
            "flags": flags,
            "request_id": request_id,
            "body_length": body_len,
            "hmac_tag": tag.hex(),
            "actual_body_length": len(data) - HEADER_SIZE,
            "body_hex": data[HEADER_SIZE:].hex(),
        }
    )
    try:
        header_frame, declared_length = parse_header(
            data[:HEADER_SIZE],
            max_frame_size=max_frame_size,
        )
        report["message_type"] = header_frame.message_type.name
        expected_size = HEADER_SIZE + declared_length
        if len(data) != expected_size:
            relation = "truncated" if len(data) < expected_size else "has trailing bytes"
            raise ValueError(f"frame {relation}: expected {expected_size} bytes, got {len(data)}")
        if key is not None:
            frame = parse_frame_bytes(data, key, max_frame_size=max_frame_size)
            report["hmac_valid"] = True
        else:
            frame = header_frame
            frame = type(frame)(
                frame.version,
                frame.message_type,
                frame.flags,
                frame.request_id,
                data[HEADER_SIZE:],
                frame.hmac_tag,
            )
        message = decode_message(frame.message_type, frame.body)
        report["decoded_body"] = _message_to_dict(message)
        report["valid"] = True
    except ProtocolError as exc:
        if key is not None:
            report["hmac_valid"] = False
        report["error"] = str(exc)
    except (ValueError, TypeError) as exc:
        if key is not None:
            report["hmac_valid"] = False
        report["error"] = str(exc)
    return report


def inspect_file(
    path: str | Path,
    *,
    key: bytes | None = None,
    max_frame_size: int = MAX_FRAME_SIZE,
) -> dict[str, Any]:
    # A single valid frame is at most HEADER_SIZE + max_frame_size bytes, so the
    # inspector never needs to read more. Bounding the read keeps it safe on a
    # hostile or accidentally huge file instead of exhausting memory.
    cap = HEADER_SIZE + max_frame_size
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(cap + 1)
    except OSError as exc:
        report: dict[str, Any] = {"valid": False, "error": f"cannot read file: {exc}"}
        if key is not None:
            report["hmac_valid"] = False
        return report
    if len(data) > cap:
        report = {
            "valid": False,
            "error": f"file is larger than a single frame can be ({cap} bytes); refusing to load",
        }
        if key is not None:
            report["hmac_valid"] = False
        return report
    return inspect_bytes(data, key=key, max_frame_size=max_frame_size)
