from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any
from ..contracts import AgentCapability, ToolCapability


class Decision(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True)
class FirewallResult:
    decision: Decision
    reason: str
    capability: ToolCapability


class ToolFirewall:
    def __init__(self, capabilities: dict[str, ToolCapability]):
        self.capabilities = dict(capabilities)

    def evaluate(self, agent: AgentCapability, tool: str, args: dict[str, Any]) -> FirewallResult:
        cap = self.capabilities.get(tool)
        if cap is None:
            cap = ToolCapability(tool, "UNKNOWN", side_effects=True)
            return FirewallResult(Decision.BLOCK, "Unknown tool fails closed.", cap)
        if not agent.can_use(tool):
            return FirewallResult(Decision.BLOCK, "Tool outside specialist scope.", cap)
        if not cap.allows_role(agent.role):
            return FirewallResult(Decision.BLOCK, "Role not authorized for tool.", cap)
        if cap.credentials:
            return FirewallResult(Decision.REVIEW, "Credential-bearing operation needs elevated approval.", cap)
        if cap.side_effects and cap.safety != "SAFE":
            return FirewallResult(Decision.REVIEW, "Side-effecting operation needs authorization.", cap)
        return FirewallResult(Decision.ALLOW, "Capability and role checks passed.", cap)
