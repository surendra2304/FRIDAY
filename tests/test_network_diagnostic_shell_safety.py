"""Regression tests for safe argument-vector network diagnostics."""

from types import SimpleNamespace

from friday.skills.builtins import network_diagnostic as module
from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill


def test_network_diagnostic_never_uses_a_shell(monkeypatch):
    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        observed.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout="64 bytes from 8.8.8.8: time=10ms",
            stderr="",
        )

    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = NetworkDiagnosticSkill().execute(user_request="diagnose my internet")

    assert observed["args"] == ["ping", "-c", "3", "8.8.8.8"]
    assert observed["shell"] is False
    assert observed["timeout"] == 10
    assert result.success is True


def test_network_diagnostic_uses_windows_ping_arguments(monkeypatch):
    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = args
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="Reply from 8.8.8.8: bytes=32", stderr="")

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = NetworkDiagnosticSkill().execute(user_request="diagnose my internet")

    assert observed["args"] == ["ping", "-n", "3", "8.8.8.8"]
    assert observed["shell"] is False
    assert result.success is True
