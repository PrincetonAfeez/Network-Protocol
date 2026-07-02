""" Init: test the public exports and version."""

from __future__ import annotations

import toyproto
from toyproto import PROTOCOL_VERSION, ToyProtoClient, ToyProtoServer


def test_public_exports() -> None:
    assert toyproto.__all__ == ["PROTOCOL_VERSION", "ToyProtoClient", "ToyProtoServer"]
    assert PROTOCOL_VERSION == 1
    assert ToyProtoClient is not None
    assert ToyProtoServer is not None


def test_version_is_installed_package_version() -> None:
    assert toyproto.__version__
    assert toyproto.__version__ != "0.0.0+unknown"
