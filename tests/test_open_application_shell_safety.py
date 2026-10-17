"""The safe application launcher must never re-enter a command shell."""

from friday.tools.builtin import open_application as module


def test_application_path_fallback_uses_direct_argv_not_shell(monkeypatch):
    observed = {}

    def unavailable_startfile(_executable):
        raise OSError("App Paths lookup unavailable")

    def fake_popen(args, **kwargs):
        observed["args"] = args
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(module.os, "startfile", unavailable_startfile, raising=False)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    tool = module.OpenApplicationTool()
    assert tool._launch("chrome.exe") is True
    assert observed["args"] == ["chrome.exe"]
    assert observed["shell"] is False
