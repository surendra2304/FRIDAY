"""Autonomous Welcome Home & Workspace Protocol for FRIDAY.

Adapted from the Jarvis welcome flow, implemented using 100% free, local,
and open-source capabilities:
1. Entrance media playback (Spotify / YouTube).
2. Multi-monitor physical display layout orchestration (snaps browser windows
   across monitors with fullscreen F11).
3. Developer workspace activation (focuses or launches Cursor / VS Code).
4. Spoken greeting via local offline Windows Native SAPI5 TTS (native_tts,
   requiring ZERO paid API keys or cloud tokens).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import Optional

from friday.core.logging import get_logger
from friday.devices.windows_friday import windows_friday
from friday.voice.native_tts import native_tts

logger = get_logger("autonomous.welcome_protocol")


@dataclass
class WelcomeProtocolConfig:
    """Configurable options for the welcome protocol.
    
    Optimized by default for a single-laptop workstation (VS Code, entrance media,
    and free offline Windows SAPI5 voice greeting).
    """

    # Entrance Media
    media_uri: str = os.environ.get(
        "FRIDAY_WELCOME_MEDIA_URI",
        "https://open.spotify.com/track/39shmbIHICJ2Wxnk1fPSdz",
    )
    play_media: bool = True

    # Developer IDE (Defaults to VS Code on single laptop)
    open_editor: bool = True
    editor: str = os.environ.get("FRIDAY_EDITOR", "vscode")
    editor_fullscreen: bool = False

    # Spoken Greeting (100% free via Windows SAPI5 / Zira)
    welcome_speech_enabled: bool = True
    welcome_phrase: str = os.environ.get(
        "FRIDAY_WELCOME_PHRASE",
        (
            "Welcome home, Surendra. All systems operational. "
            "Your workspace is ready."
        ),
    )
    speech_delay_s: float = float(os.environ.get("FRIDAY_WELCOME_SPEECH_DELAY", "1.0"))

    # Optional Web Browser Dashboard (Disabled by default on single laptop screen)
    open_browser: bool = os.environ.get("FRIDAY_WELCOME_OPEN_BROWSER", "false").lower() in ("true", "1")
    browser_url: str = os.environ.get("FRIDAY_WELCOME_BROWSER_URL", "")
    browser_monitor: int = int(os.environ.get("FRIDAY_WELCOME_BROWSER_MONITOR", "1"))
    browser_fullscreen: bool = False

    # Secondary Display Dashboard (Only active if multi-monitor hardware is physically present)
    open_secondary: bool = os.environ.get("FRIDAY_OPEN_SECONDARY", "false").lower() in ("true", "1")
    secondary_url: str = os.environ.get("FRIDAY_SECONDARY_DASHBOARD_URL", "")
    secondary_monitor: int = int(os.environ.get("FRIDAY_SECONDARY_MONITOR", "2"))

    # Compatibility parameters (legacy / external callers)
    open_claude: bool = False
    claude_url: str = ""
    claude_monitor: int = 1

    def __post_init__(self) -> None:
        """Handle legacy Claude Code parameters and browser fallback."""
        if self.open_claude:
            self.open_browser = True
        if self.claude_url and not self.browser_url:
            self.browser_url = self.claude_url
        if self.claude_monitor != 1 and self.browser_monitor == 1:
            self.browser_monitor = self.claude_monitor


class WelcomeProtocol:
    """Coordinates entrance media, browser layouts, IDE focus, and voice greeting."""

    def __init__(self, config: Optional[WelcomeProtocolConfig] = None) -> None:
        self.config = config or WelcomeProtocolConfig()
        self._running_lock = threading.Lock()
        self._last_run_timestamp: float = 0.0

    def play_media(self, uri: str) -> None:
        """Play the entrance track or media stream."""
        u = uri.strip()
        if not u:
            return
        logger.info("Playing welcome media: %s", u)
        try:
            if sys.platform == "win32":
                os.startfile(u)
            else:
                webbrowser.open(u)
        except Exception as e:
            logger.warning("Could not launch media URI %s: %s", u, e)

    def run(self, config_override: Optional[WelcomeProtocolConfig] = None) -> bool:
        """Execute the complete welcome sequence in a background-safe manner.

        Returns:
            True if executed, False if skipped due to active concurrent run.
        """
        cfg = config_override or self.config
        now = time.monotonic()

        # Prevent duplicate concurrent executions (debounce 5 seconds)
        if not self._running_lock.acquire(blocking=False):
            logger.info("Welcome protocol is already executing; skipping duplicate trigger.")
            return False

        try:
            if now - self._last_run_timestamp < 5.0:
                logger.info("Welcome protocol triggered too soon after previous run; debouncing.")
                return False

            self._last_run_timestamp = now
            logger.info("=== INITIATING FRIDAY WELCOME PROTOCOL (SINGLE-LAPTOP OPTIMIZED) ===")

            # 1. Play entrance track
            if cfg.play_media and cfg.media_uri:
                self.play_media(cfg.media_uri)

            # 2. Spoken greeting via native TTS (100% free offline Windows SAPI5)
            if cfg.welcome_speech_enabled and cfg.welcome_phrase.strip():
                def _delayed_speech() -> None:
                    if cfg.speech_delay_s > 0:
                        time.sleep(cfg.speech_delay_s)
                    native_tts.enabled = True
                    native_tts.speak(cfg.welcome_phrase.strip())

                threading.Thread(target=_delayed_speech, daemon=True, name="WelcomeTTS").start()

            # 3. Foreground or launch developer IDE (VS Code by default)
            if cfg.open_editor and cfg.editor:
                time.sleep(0.5)
                logger.info("Foregrounding editor: %s (fullscreen=%s)...", cfg.editor, cfg.editor_fullscreen)
                windows_friday.focus_or_launch_editor(
                    editor=cfg.editor,
                    fullscreen=cfg.editor_fullscreen,
                )

            # 4. Optional Web Browser Dashboard (if explicitly configured)
            if cfg.open_browser and cfg.browser_url:
                logger.info("Opening workspace browser on monitor %d...", cfg.browser_monitor)
                windows_friday.launch_browser_on_monitor(
                    url=cfg.browser_url,
                    monitor_index=cfg.browser_monitor,
                    fullscreen=cfg.browser_fullscreen,
                )

            # 5. Secondary Web Dashboard (only if multi-monitor hardware is physically present)
            monitors = windows_friday.get_sorted_monitors()
            if cfg.open_secondary and cfg.secondary_url and len(monitors) > 1:
                logger.info("Opening Secondary Dashboard on monitor %d...", cfg.secondary_monitor)
                windows_friday.launch_browser_on_monitor(
                    url=cfg.secondary_url,
                    monitor_index=cfg.secondary_monitor,
                    fullscreen=cfg.browser_fullscreen,
                )

            logger.info("=== FRIDAY WELCOME PROTOCOL COMPLETED ===")
            return True

        except Exception as e:
            logger.error("Error running welcome protocol: %s", e)
            return False
        finally:
            self._running_lock.release()


# Global singleton instance
welcome_protocol = WelcomeProtocol()
