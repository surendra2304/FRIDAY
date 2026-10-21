"""Regression tests for the repository verification entrypoint."""
from __future__ import annotations

import subprocess
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import scripts.run_verification as verification


def test_run_pytest_uses_the_current_repository_and_not_a_windows_path(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="12 passed\n", stderr="")

    monkeypatch.setattr(verification.subprocess, "run", fake_run)

    output = verification.run_pytest()

    command, kwargs = calls[0]
    assert output == "12 passed\n"
    assert command[0] == verification.sys.executable
    assert command[-1] == str(verification.ROOT / "tests")
    assert kwargs["cwd"] == verification.ROOT
    assert "d:/FRIDAY/tests" not in command
    assert command[1:3] == ["-m", "pytest"]
    assert command.count("-m") == 1


def test_live_tests_are_selected_only_by_the_explicit_live_runner(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="2 passed\n", stderr="")

    monkeypatch.setattr(verification.subprocess, "run", fake_run)

    verification.run_real_gemini_tests()

    command, kwargs = calls[0]
    assert command[-3:-1] == ["-m", "live"]
    assert command[-1] == str(verification.ROOT / "tests")
    assert kwargs["cwd"] == verification.ROOT


def test_main_does_not_run_live_tests_without_explicit_opt_in(monkeypatch):
    normal_tests = MagicMock()
    live_tests = MagicMock()
    monkeypatch.setattr(verification, "run_security_check", lambda root: True)
    monkeypatch.setattr(verification, "monitor_performance", lambda **kwargs: nullcontext())
    monkeypatch.setattr(verification, "run_pytest", normal_tests)
    monkeypatch.setattr(verification, "run_real_gemini_tests", live_tests)

    assert verification.main([]) == 0

    normal_tests.assert_called_once_with()
    live_tests.assert_not_called()


def test_main_runs_live_tests_when_explicitly_requested(monkeypatch):
    normal_tests = MagicMock()
    live_tests = MagicMock()
    monkeypatch.setattr(verification, "run_security_check", lambda root: True)
    monkeypatch.setattr(verification, "monitor_performance", lambda **kwargs: nullcontext())
    monkeypatch.setattr(verification, "run_pytest", normal_tests)
    monkeypatch.setattr(verification, "run_real_gemini_tests", live_tests)

    assert verification.main(["--include-live"]) == 0

    normal_tests.assert_called_once_with()
    live_tests.assert_called_once_with()


def test_main_stops_before_tests_when_security_check_fails(monkeypatch):
    normal_tests = MagicMock()
    monkeypatch.setattr(verification, "run_security_check", lambda root: False)
    monkeypatch.setattr(verification, "run_pytest", normal_tests)

    assert verification.main([]) == 1
    normal_tests.assert_not_called()


def test_pytest_failure_preserves_the_exit_code_and_diagnostics(monkeypatch):
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=2, stdout="1 failed\n", stderr="collection error")

    monkeypatch.setattr(verification.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError) as raised:
        verification.run_pytest()

    assert raised.value.returncode == 2
    assert raised.value.output == "1 failed\n"
    assert raised.value.stderr == "collection error"


def test_script_security_entrypoint_reuses_the_root_scanner():
    import security_check
    from scripts import security_check as script_security

    assert script_security.run_security_check is security_check.run_security_check
    assert script_security.SECRET_PATTERNS is security_check.SECRET_PATTERNS
