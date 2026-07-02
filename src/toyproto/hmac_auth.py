"""HMAC-SHA256 helpers for canonical ToyProto frame bytes."""
 
from __future__ import annotations

import hashlib
import hmac

from .constants import HMAC_SIZE


def compute_tag(key: bytes, canonical_frame: bytes) -> bytes:
    if not key:
        raise ValueError("shared key must not be empty")
    return hmac.new(key, canonical_frame, hashlib.sha256).digest()


def verify_tag(key: bytes, canonical_frame: bytes, received_tag: bytes) -> bool:
    if len(received_tag) != HMAC_SIZE:
        return False
    expected = compute_tag(key, canonical_frame)
    return hmac.compare_digest(expected, received_tag)

