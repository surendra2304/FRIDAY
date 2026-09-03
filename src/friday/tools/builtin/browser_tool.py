"""Browser Automation Tool for FRIDAY's canonical ToolRegistry.

Enables FRIDAY to interact with websites, inspect web application state,
and extract information under strict browser safety policies.
"""

from __future__ import annotations

from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.integrations.browser_use.executor import BrowserUseExecutor
from friday.tools.base import BaseTool


class BrowserAutomationTool(BaseTool):
    """Natively registers browser automation capability into FRIDAY's ToolRegistry."""

    def __init__(self, executor: BrowserUseExecutor | None = None) -> None:
        self.executor = executor or BrowserUseExecutor()

    @property
    def name(self) -> str:
        return "browser_action"

    @property
    def description(self) -> str:
        return (
            "Automates browser actions: navigate to a URL, extract page content, "
            "inspect page state, capture screenshots, or click/type on web elements."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: 'navigate', 'extract', 'screenshot', 'click', 'type'",
                    "enum": ["navigate", "extract", "screenshot", "click", "type"],
                },
                "url": {
                    "type": "string",
                    "description": "The URL to open or inspect.",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector or element identifier for click/type actions.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into an input element.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query if URL is not known.",
                },
            },
            "required": ["action"],
        }

    @property
    def safety_level(self) -> SafetyLevel:
        return SafetyLevel.SAFE

    def execute(self, **kwargs: Any) -> ToolResult:
        res = self.executor.execute(kwargs)
        if res.success:
            return ToolResult(
                name=self.name,
                content=str(res.output),
                is_error=False,
                safety_level=self.safety_level,
                metadata=res.metadata,
            )
        return ToolResult(
            name=self.name,
            content=res.error or "Browser action failed.",
            is_error=True,
            safety_level=self.safety_level,
            metadata=res.metadata,
        )
