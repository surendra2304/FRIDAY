import sys
from types import SimpleNamespace

from friday.devices import app_launcher
from friday.tools.builtin import close_application
from friday.tools.builtin.close_application import CloseApplicationTool


def test_open_chrome_focuses_existing_window_without_spawning_another(monkeypatch):
    monkeypatch.setattr(app_launcher, "find_existing_window", lambda keywords, classes: 123)
    monkeypatch.setattr(app_launcher, "force_window_foreground", lambda hwnd: True)
    monkeypatch.setattr(app_launcher, "_remains_foreground", lambda hwnd: True)
    monkeypatch.setattr(
        app_launcher,
        "find_all_installations",
        lambda key: (_ for _ in ()).throw(AssertionError("existing Chrome should be reused")),
    )

    success, receipt = app_launcher.launch_desktop_app("Chrome")

    assert success is True
    assert "Brought active Google Chrome to front" in receipt


def test_close_application_verifies_graceful_window_close(monkeypatch):
    state = {"open": True}

    def matching(_title):
        if state["open"]:
            return [101]
        return []

    def post_message(_hwnd, _message, _wparam, _lparam):
        state["open"] = False

    monkeypatch.setattr(close_application, "_native_matching_windows", matching)
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(PostMessage=post_message))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(WM_CLOSE=16))

    result = CloseApplicationTool().execute(window_title="Notepad")

    assert result.is_error is False
    assert "Windows confirmed no matching visible window remains" in result.content


def test_close_application_does_not_claim_success_when_window_remains(monkeypatch):
    monkeypatch.setattr(close_application, "_native_matching_windows", lambda title: [42])
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(PostMessage=lambda *args: None))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(WM_CLOSE=16))
    monkeypatch.setattr(close_application.time, "sleep", lambda _: None)

    result = CloseApplicationTool().execute(window_title="Chrome")

    assert result.is_error is True
    assert "could not confirm it closed" in result.content


def test_open_application_does_not_retry_when_os_started_but_focus_failed(monkeypatch):
    from friday.devices import app_launcher
    from friday.tools.builtin import open_application

    monkeypatch.setattr(
        app_launcher,
        "launch_desktop_app",
        lambda name: (False, "Chrome started; Windows did not keep it in front."),
    )
    monkeypatch.setattr(open_application.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("duplicate launch")))

    result = open_application.OpenApplicationTool().execute(application="chrome")

    assert result.is_error is True
    assert result.metadata == {"launch_requested": True, "verified_visible": False}


def test_open_application_does_not_retry_unverified_generic_launch(monkeypatch):
    from friday.devices import app_launcher
    from friday.tools.builtin import open_application

    monkeypatch.setattr(
        app_launcher,
        "launch_desktop_app",
        lambda name: (False, "Some App started, but FRIDAY could not verify a visible application window."),
    )
    monkeypatch.setattr(
        open_application.OpenApplicationTool,
        "_resolve_executable",
        lambda self, name: "some-app.exe",
    )
    monkeypatch.setattr(
        open_application.OpenApplicationTool,
        "_launch",
        lambda self, executable: (_ for _ in ()).throw(AssertionError("must not retry an unverified launch")),
    )

    result = open_application.OpenApplicationTool().execute(application="Some App")

    assert result.is_error is True
    assert result.metadata == {"launch_requested": True, "verified_visible": False}


def test_windows_directive_routes_close_tab_to_browser_handler(monkeypatch):
    from friday.devices.windows_friday import windows_friday

    monkeypatch.setattr(
        app_launcher,
        "close_active_chrome_tab",
        lambda: (True, "Closed the active Chrome tab; Windows confirmed its window closed."),
    )

    assert windows_friday.can_handle("close the tab") is True
    handled, receipt, metadata = windows_friday.handle_directive("close the tab")

    assert handled is True
    assert metadata["action"] == "close_chrome_tab"
    assert metadata["success"] is True
    assert "Windows confirmed" in receipt
