"""Next-generation external agent capability integrations for FRIDAY.

Provides clean bridges to Browser Use, Mem0, Model Context Protocol (MCP),
and mini-SWE-agent, all adhering to FRIDAY's single-brain architecture, canonical
ToolRegistry, and strict security boundary.
"""

from friday.integrations.nextgen.browser_use import BrowserUseBridge
from friday.integrations.nextgen.mcp import MCPBridge
from friday.integrations.nextgen.mem0 import Mem0MemoryBridge
from friday.integrations.nextgen.mini_swe_agent import MiniSWEAgentBridge

__all__ = [
    "BrowserUseBridge",
    "MCPBridge",
    "Mem0MemoryBridge",
    "MiniSWEAgentBridge",
]
