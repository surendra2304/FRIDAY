"""MCP Tool Adapter for FRIDAY's ToolRegistry.

Converts external Model Context Protocol (MCP) tool schemas into first-class
native FRIDAY `BaseTool` instances, ensuring all external tools seamlessly adhere
to FRIDAY parameter validation, authorization, and safety levels.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.mcp.adapter")


class MCPToolAdapter(BaseTool):
    """Adapts an external MCP Tool into a native FRIDAY BaseTool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any],
        call_fn: Callable[[str, dict[str, Any]], Any],
        server_name: str = "mcp_server",
        safety_level: SafetyLevel = SafetyLevel.SENSITIVE,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._name = name
        self._description = description or f"External MCP tool provided by {server_name}"
        self._parameters = parameters_schema or {"type": "object", "properties": {}}
        self._call_fn = call_fn
        self.server_name = server_name
        self._safety_level = safety_level
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @property
    def safety_level(self) -> SafetyLevel:
        return self._safety_level

    def execute(self, **kwargs: Any) -> ToolResult:
        """Synchronously execute the external MCP tool with bounded timeout."""
        try:
            logger.info(f"Invoking MCP tool '{self.name}' on server '{self.server_name}' with args: {list(kwargs.keys())}")
            raw_res = self._call_fn(self.name, kwargs)

            # Handle async call_fn if returned coroutine
            if asyncio.iscoroutine(raw_res):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        raw_res = pool.submit(asyncio.run, raw_res).result(timeout=self.timeout_seconds)
                else:
                    raw_res = loop.run_until_complete(asyncio.wait_for(raw_res, timeout=self.timeout_seconds))

            # Normalize MCP result
            content = ""
            if hasattr(raw_res, "content"):
                items = getattr(raw_res, "content", [])
                parts = []
                for item in items:
                    if hasattr(item, "text"):
                        parts.append(item.text)
                    elif isinstance(item, dict) and "text" in item:
                        parts.append(item["text"])
                    else:
                        parts.append(str(item))
                content = "\n".join(parts)
            elif isinstance(raw_res, dict):
                content = str(raw_res.get("content") or raw_res.get("result") or raw_res)
            else:
                content = str(raw_res)

            is_error = getattr(raw_res, "isError", False)
            return ToolResult(
                name=self.name,
                content=content or ("Success" if not is_error else "Error"),
                is_error=bool(is_error),
                safety_level=self.safety_level,
                metadata={"server": self.server_name, "mcp_tool": self.name},
            )
        except Exception as e:
            logger.exception(f"MCP tool execution failed: {e}")
            return ToolResult(
                name=self.name,
                content=f"MCP invocation failed on '{self.name}': {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
                metadata={"server": self.server_name},
            )
