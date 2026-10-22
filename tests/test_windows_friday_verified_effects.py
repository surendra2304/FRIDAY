"""WindowsFridayController must not mistake a launch attempt for a launch."""

from __future__ import annotations

from typing import Any

import pytest

from friday.core.effects import EffectOutcome
from friday.devices import windows_friday as wf
from friday.devices.windows_friday import windows_friday


_FAILED = EffectOutcome(False, "offline fixture rejected process start", {"returncode": 127})


@pytest.mark.parametrize(
    ("app_name", "expected_command"),
    [
        ("camera", "start microsoft.windows.camera:"),
        ("snipping tool", "start ms-screenclip:"),
        ("control panel", "control"),
        ("task manager", "taskmgr"),
        ("terminal", "wt"),
        ("cmd", "start cmd.exe"),
        ("powershell", "start powershell.exe"),
    ],
)
def test_named_app_launches_report_a_failed_process_start(
    monkeypatch, app_name: str, expected_command: str
) -> None:
    """Every hard-coded shell launcher checks the result it reports to the user."""
    commands: list[str] = []
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda command, **_kwargs: commands.append(command) or _FAILED,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    success, reply = windows_friday.launch_app(app_name)

    assert commands == [expected_command]
    assert success is False
    assert "Could not open" in reply


def test_chrome_path_launch_checks_the_executable_result(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(wf, "get_chrome_path", lambda: "/offline/chrome")
    monkeypatch.setattr(
        "friday.core.effects.launch_argv_verified",
        lambda argv, **_kwargs: calls.append(list(argv)) or _FAILED,
        raising=False,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    success, reply = windows_friday.launch_app("chrome")

    assert calls == [["/offline/chrome"]]
    assert success is False
    assert "Could not open Google Chrome" in reply


def test_application_launch_failure_stays_on_the_directive_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda _command, **_kwargs: _FAILED,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    handled, reply, metadata = windows_friday.handle_directive("open camera")

    assert handled is True
    assert metadata["action"] == "launch_app"
    assert metadata["app"] == "camera"
    assert metadata["success"] is False
    assert "Could not open Camera" in reply


def test_settings_directive_propagates_failed_launch_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda command, **_kwargs: _FAILED,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    handled, reply, metadata = windows_friday.handle_directive("open settings")

    assert handled is True
    assert metadata["action"] == "open_settings"
    assert metadata["success"] is False
    assert "Could not open Windows Settings" in reply


def test_screenshot_fallback_does_not_claim_that_a_screenshot_was_captured(monkeypatch) -> None:
    from PIL import ImageGrab

    def unavailable() -> Any:
        raise OSError("desktop capture is unavailable in this runner")

    monkeypatch.setattr(ImageGrab, "grab", unavailable)
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda command, **_kwargs: _FAILED,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    success, reply, image = windows_friday.take_screenshot()

    assert success is False
    assert image is None
    assert "no screenshot was captured" in reply.lower()
    assert "offline fixture rejected process start" in reply


def test_sleep_directive_reports_failed_suspend_launch(monkeypatch) -> None:
    monkeypatch.setattr(
        "friday.core.effects.launch_process_verified",
        lambda command, **_kwargs: _FAILED,
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())

    handled, reply, metadata = windows_friday.handle_directive("put laptop to sleep")

    assert handled is True
    assert metadata["action"] == "sleep_laptop"
    assert metadata["success"] is False
    assert "Could not put laptop to sleep" in reply


def test_monitor_url_open_reports_browser_rejection(monkeypatch) -> None:
    monkeypatch.setattr(wf, "get_chrome_path", lambda: None)
    monkeypatch.setattr(wf.webbrowser, "open", lambda _url: False)

    success, reply = windows_friday.launch_browser_on_monitor("https://example.invalid")

    assert success is False
    assert "Nothing was opened" in reply


def test_monitor_url_open_reports_both_chrome_and_browser_fallback_failure(monkeypatch) -> None:
    monkeypatch.setattr(wf, "get_chrome_path", lambda: "/offline/chrome")
    monkeypatch.setattr(windows_friday, "_get_chrome_hwnds", lambda: set())
    monkeypatch.setattr(
        "friday.core.effects.launch_argv_verified",
        lambda _argv, **_kwargs: _FAILED,
        raising=False,
    )
    monkeypatch.setattr(
        "friday.core.effects.open_url_verified",
        lambda _url: EffectOutcome(False, "browser stand-in rejected URL", {"opened": False}),
    )
    monkeypatch.setattr(wf.subprocess, "Popen", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wf.webbrowser, "open", lambda _url: False)

    success, reply = windows_friday.launch_browser_on_monitor("https://example.invalid")

    assert success is False
    assert "browser stand-in rejected URL" in reply
