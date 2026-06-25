"""ToyProto: a small defensive framed protocol over TCP."""

from importlib.metadata import PackageNotFoundError, version

from .client import ToyProtoClient
from .constants import PROTOCOL_VERSION
from .server import ToyProtoServer

try:
    # Single source of truth: the version declared in pyproject.toml.
    __version__ = version("toyproto-lab")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled tree
    __version__ = "0.0.0+unknown"

__all__ = ["PROTOCOL_VERSION", "ToyProtoClient", "ToyProtoServer"]

