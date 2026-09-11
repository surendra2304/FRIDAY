"""Open Application tool: launch known Windows applications by spoken or typed name.

Bridges voice/text intents ("open notepad") to native app launching via
os.startfile (App Paths resolution) with a subprocess PATH fallback. Shell
and console applications are refused — they require explicit text-mode
authorization through the sensitive-action path.
"""

import os
import subprocess
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.vision.intent_detector import IntentDetector

logger = get_logger("tools.open_application")

# Applications that must NOT be launched via the SAFE voice/text tool path
_BLOCKED_APPLICATIONS = {"cmd.exe", "powershell.exe", "wt.exe", "taskmgr.exe"}

APP_LAUNCH_MAP = IntentDetector.APP_LAUNCH_MAP


class OpenApplicationTool(BaseTool):
    """Launch a known Windows application by name (e.g. 'notepad', 'calculator', 'word', 'excel', 'wordpad', 'paint')."""

    name = "open_application"
    description = (
        "Open a Windows application by its common name (e.g. 'notepad', 'calculator', "
        "'paint', 'file explorer', 'edge', 'chrome', 'word', 'excel', 'wordpad', 'microsoft store'). Use this whenever the user asks "
        "to open, launch, or start an application."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "The application name the user asked to open (e.g. 'notepad').",
            }
        },
        "required": ["application"],
    }

    def _resolve_executable(self, application: str) -> str:
        """Map a spoken/typed application name to an executable or full binary path."""
        app = (application or "").strip().lower()

        # Known absolute paths for standard Windows software that might not be in PATH
        known_system_paths = {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "google chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "microsoft edge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "code": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
            ],
            "vscode": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
            ],
        }

        # Check explicit path candidates first
        for key, paths in known_system_paths.items():
            if key in app or app in key:
                for candidate in paths:
                    if os.path.exists(candidate):
                        return candidate

        if app in IntentDetector.APP_LAUNCH_MAP:
            return IntentDetector.APP_LAUNCH_MAP[app]
        # Substring match on known names ("the notepad app")
        for known, exe in IntentDetector.APP_LAUNCH_MAP.items():
            if known in app:
                return exe

        # Fuzzy match on known names to tolerate typos (e.g. 'whatsaapp' -> 'whatsapp')
        import difflib
        matches = difflib.get_close_matches(app, IntentDetector.APP_LAUNCH_MAP.keys(), n=1, cutoff=0.6)
        if matches:
            return IntentDetector.APP_LAUNCH_MAP[matches[0]]

        return ""

    def _launch(self, executable: str) -> bool:
        """Launch natively via direct executable spawn, App Paths, or shell."""
        try:
            # If web URL, open in default browser
            if executable.startswith("http://") or executable.startswith("https://"):
                import webbrowser
                webbrowser.open(executable)
                return True

            # If absolute path that exists, spawn directly
            if os.path.isabs(executable) and os.path.exists(executable):
                subprocess.Popen([executable])
                return True

            if not executable.lower().endswith(".exe"):
                os.startfile(executable)  # protocol URIs e.g. ms-settings:
                return True

            try:
                os.startfile(executable)
                return True
            except OSError:
                logger.warning(f"App Paths/ShellExecute failed for '{executable}'; trying PATH via shell.")

            subprocess.Popen([executable] if not executable.endswith(".exe") else executable, shell=True)
            return True
        except Exception as e:
            logger.error(f"Failed to launch '{executable}': {e}")
            return False

    def execute(self, application: str = "", **kwargs: Any) -> ToolResult:
        requested = (application or "").strip()
        if not requested:
            return ToolResult(
                name=self.name, content="No application name provided.", is_error=True,
                safety_level=self.safety_level,
            )

        # Try robust Windows desktop launcher first with CIM + foreground lock bypass
        try:
            from friday.devices.app_launcher import launch_desktop_app
            ok, msg = launch_desktop_app(requested)
            if ok:
                logger.info(f"Opened application '{requested}' via app_launcher: {msg}")
                return ToolResult(
                    name=self.name,
                    content=msg,
                    is_error=False,
                    safety_level=self.safety_level,
                )
        except Exception as e:
            logger.warning(f"app_launcher fallback for '{requested}': {e}")

        executable = self._resolve_executable(requested)
        if not executable:
            known = ", ".join(sorted(IntentDetector.APP_LAUNCH_MAP.keys()))
            return ToolResult(
                name=self.name,
                content=f"Unknown application '{requested}'. Known applications: {known}.",
                is_error=True,
                safety_level=self.safety_level,
            )

        if executable.lower() in _BLOCKED_APPLICATIONS:
            return ToolResult(
                name=self.name,
                content=(
                    f"'{requested}' is a shell/console application and cannot be opened "
                    "via this tool. Shells require explicit text-mode authorization."
                ),
                is_error=True,
                safety_level=self.safety_level,
            )

        if self._launch(executable):
            logger.info(f"Opened application '{requested}' ({executable})")
            return ToolResult(
                name=self.name,
                content=f"Opened {requested}.",
                is_error=False,
                safety_level=self.safety_level,
            )
        return ToolResult(
            name=self.name,
            content=f"Failed to open {requested} ({executable}).",
            is_error=True,
            safety_level=self.safety_level,
        )
