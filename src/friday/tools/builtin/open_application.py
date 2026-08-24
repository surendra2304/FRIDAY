# -*- coding: utf-8 -*-
"""Open Application tool: launch known Windows applications by spoken or typed name.

Bridges voice/text intents ("open notepad") to native app launching via
os.startfile (App Paths resolution) with a subprocess PATH fallback. Shell
and console applications are refused — they require explicit text-mode
authorization through the sensitive-action path.
"""

import os
import subprocess
from typing import Any, Dict

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
        "'paint', 'file explorer', 'edge', 'chrome', 'word', 'excel', 'wordpad'). Use this whenever the user asks "
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
        """Map a spoken/typed application name to an executable."""
        app = (application or "").strip().lower()
        if app in IntentDetector.APP_LAUNCH_MAP:
            return IntentDetector.APP_LAUNCH_MAP[app]
        # Substring match on known names ("the notepad app")
        for known, exe in IntentDetector.APP_LAUNCH_MAP.items():
            if known in app:
                return exe
        return ""

    def _launch(self, executable: str) -> bool:
        """Launch natively: App Paths via ShellExecute, then PATH via shell."""
        try:
            if not executable.lower().endswith(".exe"):
                os.startfile(executable)  # protocol URIs e.g. ms-settings:
                return True
            try:
                os.startfile(executable)
                return True
            except OSError:
                logger.warning(f"App Paths/ShellExecute failed for '{executable}'; trying PATH via shell.")
            subprocess.Popen(executable, shell=True)
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
