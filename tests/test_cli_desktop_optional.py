"""Desktop-extra CLI guidance when a native Qt dependency is missing."""

from __future__ import annotations

import builtins
import importlib
import sys
from types import SimpleNamespace


def test_desktop_cli_names_native_runtime_requirements(monkeypatch, capsys) -> None:
    cli = importlib.import_module("friday.cli.main")
    monkeypatch.setattr(sys, "argv", ["friday", "--desktop"])
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(voice_enabled=False, log_level="ERROR", log_file=None),
    )
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)

    real_import = builtins.__import__

    def import_without_opengl(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "friday.desktop.app":
            raise ImportError("libGL.so.1: cannot open shared object file")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_opengl)

    result = cli.main()

    assert result == 1
    output = capsys.readouterr().out
    assert "Desktop UI could not load" in output
    assert "if PyQt6 is missing" in output
    assert "host Qt/OpenGL libraries such as libGL.so.1" in output
