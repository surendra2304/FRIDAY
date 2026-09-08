from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from ..contracts import ToolCapability, AgentCapability
from ..security.tool_firewall import ToolFirewall, Decision


@dataclass(frozen=True)
class MCPDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    capability: ToolCapability


class MCPGateway:
    def __init__(self, firewall: ToolFirewall):
        self.firewall = firewall
        self.tools = {}

    def register(self, d: MCPDescriptor):
        self.tools[d.name] = d
        self.firewall.capabilities[d.name] = d.capability

    def authorize(self, agent: AgentCapability, name, args):
        return self.firewall.evaluate(agent, name, args)

    def schema(self, name):
        d = self.tools[name]
        return {
            "name": d.name,
            "description": d.description,
            "inputSchema": d.input_schema,
            "fridaySafety": d.capability.safety,
        }

    def wrap(self, d: MCPDescriptor, callable_: Callable):
        def wrapped(**kwargs):
            return callable_(**kwargs)

        wrapped.__name__ = "mcp_" + d.name
        return wrapped
