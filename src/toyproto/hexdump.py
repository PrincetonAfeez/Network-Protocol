"""Human-readable raw frame output."""
 
from __future__ import annotations

from .constants import HEADER_SIZE, HEADER_STRUCT


def hex_lines(data: bytes, *, width: int = 16) -> str:
    lines: list[str] = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_part = " ".join(f"{byte:02x}" for byte in chunk)
        text_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"{offset:08x}  {hex_part:<{width * 3 - 1}}  |{text_part}|")
    return "\n".join(lines)


def describe_raw_frame(data: bytes) -> str:
    lines = [f"raw frame: {len(data)} bytes"]
    if len(data) >= HEADER_SIZE:
        magic, version, raw_type, flags, request_id, body_len, tag = HEADER_STRUCT.unpack(
            data[:HEADER_SIZE]
        )
        lines.extend(
            [
                f"  magic:      {magic!r}",
                f"  version:    {version}",
                f"  type:       0x{raw_type:02x}",
                f"  flags:      0x{flags:04x}",
                f"  request_id: {request_id}",
                f"  body_len:   {body_len}",
                f"  hmac:       {tag.hex()}",
                f"  body:       {data[HEADER_SIZE:].hex() or '<empty>'}",
            ]
        )
    else:
        lines.append(f"  truncated header: {len(data)}/{HEADER_SIZE} bytes")
    lines.append(hex_lines(data))
    return "\n".join(lines)

