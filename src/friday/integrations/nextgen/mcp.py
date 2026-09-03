"""MCP Client Bridge for FRIDAY.

Connects to MCPManager and MCPToolAdapter, ensuring external MCP tools
map seamlessly into FRIDAY's canonical ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from friday.tools.mcp.adapter import MCPToolAdapter
from friday.tools.mcp.manager import MCPManager, MCPServerConfig
from friday.tools.registry import ToolRegistry


class MCPBridge:
    """Bridge for configuring and discovering external MCP servers."""

    def __init__(self, manager: MCPManager | None = None) -> None:
        self.manager = manager or MCPManager()

    @property
    def sdk_available(self) -> bool:
        return self.manager.has_mcp_sdk

    def register_server(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        registry: ToolRegistry | None = None,
    ) -> list[MCPToolAdapter]:
        config = MCPServerConfig(name=name, command=command, env=env or {})
        return self.manager.discover_and_register_tools(config, registry=registry)
