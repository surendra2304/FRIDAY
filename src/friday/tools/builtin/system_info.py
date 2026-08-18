"""Safe built-in tool for retrieving local system information."""

import platform
import sys
from datetime import datetime, timezone
from typing import Any
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class SystemInfoTool(BaseTool):
    """Tool to query local system environment, OS, and Python details safely."""

    name = "get_system_info"
    description = "Retrieve basic operating system, architecture, time, and Python runtime info."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version.split()[0],
            "current_utc_time": datetime.now(timezone.utc).isoformat(),
        }
        formatted = "\n".join(f"- **{k}**: {v}" for k, v in info.items())
        return ToolResult(
            name=self.name,
            content=f"### System Information\n{formatted}",
            is_error=False,
            safety_level=self.safety_level,
        )
