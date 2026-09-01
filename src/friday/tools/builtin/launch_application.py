"""Universal Application Launcher tool for FRIDAY.

Provides flexible, direct launching of applications, executable paths,
Windows protocol URIs (e.g. 'ms-settings:', 'calculator:'), and system tools
with optional arguments and working directory.
"""

import os
import subprocess
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.vision.intent_detector import IntentDetector

logger = get_logger("tools.launch_application")

_FORBIDDEN_EXECUTABLES = {"format.com", "diskpart.exe", "reg.exe"}


class LaunchApplicationTool(BaseTool):
    """Universal Application Launcher tool for opening arbitrary applications or URIs."""

    name = "launch_application"
    description = (
        "Launch any Windows application by executable name, absolute file path, or Windows URI scheme "
        "(e.g. 'notepad', 'C:\\Program Files\\app.exe', 'ms-settings:', 'calculator:'). "
        "Accepts optional command-line arguments and working directory."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "application": {
                "type": "string",
                "description": "Application executable name, full path, or URI scheme (e.g. 'notepad', 'ms-settings:').",
            },
            "arguments": {
                "type": "string",
                "description": "Optional command-line arguments to pass to the launched application.",
            },
            "working_directory": {
                "type": "string",
                "description": "Optional working directory in which to start the application.",
            },
        },
        "required": ["application"],
    }

    def _resolve(self, application: str) -> str:
        app = (application or "").strip()
        if not app:
            return ""
        if app.startswith("ms-") or ":" in app and "/" not in app and "\\" not in app:
            return app
        low = app.lower()
        if low in IntentDetector.APP_LAUNCH_MAP:
            return IntentDetector.APP_LAUNCH_MAP[low]
        return app

    def execute(
        self,
        application: str = "",
        arguments: str = "",
        working_directory: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        target = self._resolve(application)
        if not target:
            return ToolResult(
                name=self.name,
                content="No application specified to launch.",
                is_error=True,
                safety_level=self.safety_level,
            )

        exe_base = os.path.basename(target).lower()
        if exe_base in _FORBIDDEN_EXECUTABLES:
            return ToolResult(
                name=self.name,
                content=f"Launching '{exe_base}' is restricted for safety reasons.",
                is_error=True,
                safety_level=self.safety_level,
            )

        cwd = working_directory if (working_directory and os.path.isdir(working_directory)) else None
        args_str = arguments.strip() if arguments else ""

        # 1. Windows URI scheme (e.g. ms-settings:, calculator:)
        if target.startswith("ms-") or (":" in target and not os.path.isabs(target)):
            try:
                subprocess.Popen(["explorer.exe", target], cwd=cwd, shell=False)
                return ToolResult(
                    name=self.name,
                    content=f"Launched '{target}'.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            except Exception as e:
                return ToolResult(
                    name=self.name,
                    content=f"Failed to launch URI '{target}': {e}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        # 2. Try os.startfile for Windows native resolution (if no extra args)
        if hasattr(os, "startfile") and not args_str:
            try:
                os.startfile(target)
                return ToolResult(
                    name=self.name,
                    content=f"Opened '{target}'.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            except Exception:
                pass

        # 3. Subprocess execution
        try:
            cmd = f'"{target}" {args_str}'.strip() if args_str else f'"{target}"'
            subprocess.Popen(cmd, cwd=cwd, shell=True)
            return ToolResult(
                name=self.name,
                content=f"Launched '{target}'.",
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Failed to launch '{target}': {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
