"""Unit tests for FRIDAY Autonomous Welcome Protocol and Workspace Automation."""

from unittest.mock import MagicMock, patch
import pytest

from friday.autonomous.welcome_protocol import (
    WelcomeProtocol,
    WelcomeProtocolConfig,
    welcome_protocol,
)
from friday.devices.windows_friday import windows_friday


def test_welcome_protocol_config_defaults() -> None:
    config = WelcomeProtocolConfig()
    assert config.play_media is True
    assert config.open_editor is True
    assert config.editor == "vscode"
    assert config.editor_fullscreen is False
    assert config.open_browser is False
    assert config.open_secondary is False
    assert config.open_claude is False
    assert config.welcome_speech_enabled is True
    assert "Surendra" in config.welcome_phrase or "Welcome home" in config.welcome_phrase


def test_welcome_protocol_play_media_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    launched = []
    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.os.startfile",
        lambda uri: launched.append(uri),
        raising=False,
    )
    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.webbrowser.open",
        lambda uri: launched.append(uri),
    )

    protocol = WelcomeProtocol()
    protocol.play_media("https://open.spotify.com/track/test123")
    assert len(launched) == 1
    assert "spotify" in launched[0]


def test_welcome_protocol_single_laptop_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    actions = []

    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.os.startfile",
        lambda uri: actions.append(f"media:{uri}"),
        raising=False,
    )
    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.webbrowser.open",
        lambda uri: actions.append(f"media:{uri}"),
    )
    monkeypatch.setattr(
        windows_friday,
        "get_sorted_monitors",
        lambda: [(0, 0, 1536, 864)],
    )
    monkeypatch.setattr(
        windows_friday,
        "launch_browser_on_monitor",
        lambda url, monitor_index, fullscreen: (
            actions.append(f"browser:mon{monitor_index}:{url}"),
            (True, "ok"),
        )[1],
    )
    monkeypatch.setattr(
        windows_friday,
        "focus_or_launch_editor",
        lambda editor, fullscreen: (
            actions.append(f"editor:{editor}:fs={fullscreen}"),
            (True, "ok"),
        )[1],
    )

    spoken = []
    monkeypatch.setattr(
        "friday.voice.native_tts.native_tts.speak",
        lambda phrase: spoken.append(phrase),
    )

    cfg = WelcomeProtocolConfig(
        speech_delay_s=0.0,
    )

    protocol = WelcomeProtocol(config=cfg)
    ok = protocol.run()

    assert ok is True
    # Entrance music launched
    assert any("media:https://open.spotify.com" in a for a in actions)
    # VS Code editor focused with clean maximize (not fullscreen F11)
    assert any("editor:vscode:fs=False" in a for a in actions)
    # No Claude or secondary dashboards launched on single laptop
    assert not any("browser:" in a for a in actions)
    assert not any("claude" in a for a in actions)


def test_welcome_protocol_execution_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    actions = []

    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.os.startfile",
        lambda uri: actions.append(f"media:{uri}"),
        raising=False,
    )
    monkeypatch.setattr(
        "friday.autonomous.welcome_protocol.webbrowser.open",
        lambda uri: actions.append(f"media:{uri}"),
    )
    monkeypatch.setattr(
        windows_friday,
        "get_sorted_monitors",
        lambda: [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)],
    )
    monkeypatch.setattr(
        windows_friday,
        "launch_browser_on_monitor",
        lambda url, monitor_index, fullscreen: (
            actions.append(f"browser:mon{monitor_index}:{url}"),
            (True, "ok"),
        )[1],
    )
    monkeypatch.setattr(
        windows_friday,
        "focus_or_launch_editor",
        lambda editor, fullscreen: (
            actions.append(f"editor:{editor}:fs={fullscreen}"),
            (True, "ok"),
        )[1],
    )

    spoken = []
    monkeypatch.setattr(
        "friday.voice.native_tts.native_tts.speak",
        lambda phrase: spoken.append(phrase),
    )

    cfg = WelcomeProtocolConfig(
        media_uri="https://test.media/welcome.mp3",
        open_browser=True,
        browser_url="https://dashboard.primary.test",
        browser_monitor=1,
        open_secondary=True,
        secondary_url="https://dashboard.secondary.test",
        secondary_monitor=2,
        editor="vscode",
        welcome_phrase="Welcome home Surendra.",
        speech_delay_s=0.0,
    )

    protocol = WelcomeProtocol(config=cfg)
    ok = protocol.run()

    assert ok is True
    assert any("media:https://test.media/welcome.mp3" in a for a in actions)
    assert any("browser:mon1:https://dashboard.primary.test" in a for a in actions)
    assert any("browser:mon2:https://dashboard.secondary.test" in a for a in actions)
    assert any("editor:vscode:fs=False" in a for a in actions)


def test_windows_friday_welcome_directive_handling() -> None:
    assert windows_friday.can_handle("welcome home") is True
    assert windows_friday.can_handle("run welcome protocol") is True
    assert windows_friday.can_handle("studio mode") is True

    # Test execution of welcome directive
    with patch("friday.autonomous.welcome_protocol.welcome_protocol.run") as mock_run:
        handled, reply, meta = windows_friday.handle_directive("welcome home")
        assert handled is True
        assert meta["action"] == "welcome_protocol"
        assert "Welcome home" in reply


def test_multi_monitor_bounds_and_sorting() -> None:
    monitors = windows_friday.get_sorted_monitors()
    assert len(monitors) >= 1
    # Check that each monitor is a 4-tuple of ints
    for m in monitors:
        assert len(m) == 4
        left, top, right, bottom = m
        assert right >= left
        assert bottom >= top

    # Primary monitor bounds
    b1 = windows_friday.get_monitor_bounds(1)
    assert len(b1) == 4

    # High index falls back gracefully to last monitor
    b_high = windows_friday.get_monitor_bounds(99)
    assert len(b_high) == 4
