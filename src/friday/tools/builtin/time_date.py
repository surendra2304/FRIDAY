"""Built-in tool for retrieving current system time and date."""

import datetime
import time
from typing import Any, Dict
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class TimeDateTool(BaseTool):
    """Tool to query local system time, date, day of week, and epoch timestamp."""

    name = "get_time_date"
    description = "Retrieve current local time, date, day of the week, and Unix epoch timestamp from the host system."
    safety_level = SafetyLevel.SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        now = datetime.datetime.now()
        local_time = now.strftime("%H:%M:%S")
        local_date = now.strftime("%Y-%m-%d")
        day_of_week = now.strftime("%A")
        epoch_ts = time.time()

        content = (
            f"Current Local Date: {local_date}\n"
            f"Current Local Time: {local_time}\n"
            f"Day of the Week: {day_of_week}\n"
            f"Unix Timestamp: {epoch_ts:.2f}"
        )

        return ToolResult(
            name=self.name,
            content=content,
            is_error=False,
            safety_level=self.safety_level,
        )
