""" HmacAuth: helpers for canonical ToyProto frame bytes."""

from __future__ import annotations

import pytest

from toyproto.constants import HMAC_SIZE
from toyproto.hmac_auth import compute_tag, verify_tag

KEY = b"test-key"


def test_compute_tag_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="empty"):
        compute_tag(b"", b"data")


def test_verify_tag_rejects_wrong_tag_length() -> None:
    canonical = b"canonical-bytes"
    assert verify_tag(KEY, canonical, b"short") is False


def test_verify_tag_accepts_valid_tag() -> None:
    canonical = b"canonical-bytes"
    tag = compute_tag(KEY, canonical)
    assert len(tag) == HMAC_SIZE
    assert verify_tag(KEY, canonical, tag) is True
