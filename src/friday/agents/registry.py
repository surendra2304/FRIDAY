# -*- coding: utf-8 -*-
"""Agent Registry for FRIDAY Phase 13 Multi-Agent System.

Maintains available specialist agent definitions and instances.
"""

from typing import Dict, List, Optional

from friday.agents.base_agent import BaseAgent
from friday.core.logging import get_logger

logger = get_logger("agents.registry")


class AgentRegistry:
    """Registry managing available specialist agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        """Register a specialist agent instance keyed by agent_id and role."""
        self._agents[agent.agent_id] = agent
        logger.info(f"Registered agent '{agent.role}' (ID: {agent.agent_id})")

    def get_agent(self, role_or_id: str) -> Optional[BaseAgent]:
        """Look up an agent by exact agent_id or matching role."""
        if role_or_id in self._agents:
            return self._agents[role_or_id]
        
        # Search by role case-insensitively
        target = role_or_id.lower().strip()
        for agent in self._agents.values():
            if agent.role.lower().strip() == target:
                return agent
        return None

    def list_agents(self) -> List[BaseAgent]:
        """Return all registered specialist agents."""
        return list(self._agents.values())

    def unregister_agent(self, agent_id: str) -> bool:
        """Remove an agent by ID."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    def close(self) -> None:
        """Close and clean up all specialist agents."""
        for agent in self._agents.values():
            if hasattr(agent, "close"):
                try:
                    agent.close()
                except Exception:
                    pass
        self._agents.clear()
