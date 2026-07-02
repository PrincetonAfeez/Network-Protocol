""" pytest configuration for ToyProto."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES_DIR = ROOT / "tests" / "fixtures" / "frames"


def pytest_configure(config: object) -> None:
    """Ensure binary frame fixtures exist before any test module imports them."""
    marker = FIXTURES_DIR / "valid_hello.bin"
    if marker.exists():
        return
    import subprocess

    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_frame_fixtures.py")],
        check=True,
    )
