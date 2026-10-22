"""Model Context Protocol (MCP) Client Manager for FRIDAY.

Manages connections to external MCP servers (stdio & SSE), discovers tools,
validates them against FRIDAY's security boundary, and registers them directly
into FRIDAY's canonical ToolRegistry.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from friday.core.auth import BaseAuthorizer
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.tools.mcp.adapter import MCPToolAdapter
from friday.tools.registry import ToolRegistry

logger = get_logger("tools.mcp.manager")


@dataclass
class MCPServerConfig:
    """Configuration for an external MCP server connection."""

    name: str
    command: list[str] = field(default_factory=list)
    url: str | None = None  # For SSE transport
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    default_safety_level: SafetyLevel = SafetyLevel.SENSITIVE


class MCPManager:
    """Central orchestrator for discovering, adapting, and monitoring MCP servers."""

    def __init__(self, authorizer: BaseAuthorizer | None = None) -> None:
        self.authorizer = authorizer
        self.server_configs: dict[str, MCPServerConfig] = {}
        self.adapted_tools: dict[str, MCPToolAdapter] = {}
        self._active_sessions: dict[str, Any] = {}

    @property
    def has_mcp_sdk(self) -> bool:
        """Check if official mcp Python SDK is installed."""
        try:
            import mcp  # noqa: F401
            return True
        except ImportError:
            return False

    def add_server(self, config: MCPServerConfig) -> None:
        """Register server configuration."""
        self.server_configs[config.name] = config

    def discover_and_register_tools(
        self,
        server_config: MCPServerConfig,
        registry: ToolRegistry | None = None,
    ) -> list[MCPToolAdapter]:
        """Connect to an MCP server, enumerate tools, and adapt into FRIDAY ToolRegistry."""
        self.add_server(server_config)

        if not self.has_mcp_sdk:
            logger.warning(
                f"MCP SDK is not installed. Unable to connect to MCP server '{server_config.name}'. "
                "Install with: pip install mcp"
            )
            return []

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            async def _discover():
                params = StdioServerParameters(
                    command=server_config.command[0],
                    args=server_config.command[1:],
                    env=server_config.env or None,
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        adapted = []
                        for mcp_tool in tools_result.tools:
                            # Closure for calling tool
                            def _make_caller(s_name: str, t_name: str):
                                def _call(tool_name: str, arguments: dict[str, Any]):
                                    return self._call_tool_on_server(server_config, tool_name, arguments)
                                return _call

                            adapter = MCPToolAdapter(
                                name=f"mcp_{server_config.name}_{mcp_tool.name}",
                                description=mcp_tool.description or "",
                                parameters_schema=mcp_tool.inputSchema or {},
                                call_fn=_make_caller(server_config.name, mcp_tool.name),
                                server_name=server_config.name,
                                safety_level=server_config.default_safety_level,
                                timeout_seconds=server_config.timeout_seconds,
                            )
                            adapted.append(adapter)
                        return adapted

            discovered = asyncio.run(_discover())
            for tool in discovered:
                self.adapted_tools[tool.name] = tool
                if registry:
                    registry.register(tool)
                    logger.info(f"Registered MCP tool '{tool.name}' into canonical ToolRegistry.")
            return discovered

        except Exception as e:
            logger.error(f"Failed to discover tools from MCP server '{server_config.name}': {e}")
            return []

    def _call_tool_on_server(
        self,
        config: MCPServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Invoke a tool on the target MCP server."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def _run_call():
            params = StdioServerParameters(
                command=config.command[0],
                args=config.command[1:],
                env=config.env or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.call_tool(tool_name, arguments)

        return asyncio.run(_run_call())

    def register_into_tool_registry(self, registry: ToolRegistry) -> None:
        """Register all currently adapted MCP tools into the canonical ToolRegistry."""
        for tool in self.adapted_tools.values():
            registry.register(tool)
