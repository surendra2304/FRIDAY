"""Model Context Protocol (MCP) tool integration package for FRIDAY."""

from friday.tools.mcp.adapter import MCPToolAdapter
from friday.tools.mcp.manager import MCPManager, MCPServerConfig

__all__ = [
    "MCPManager",
    "MCPServerConfig",
    "MCPToolAdapter",
]
