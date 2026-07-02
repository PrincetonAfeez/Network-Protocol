"""Main: test the __main__ module."""

from __future__ import annotations

import runpy

import pytest


def test_package_main_exits_with_cli_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toyproto.cli.main", lambda argv=None: 0)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("toyproto.__main__", run_name="__main__")
    assert exc.value.code == 0
