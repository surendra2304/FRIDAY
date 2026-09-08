"""Agents module for FRIDAY."""

from friday.agents.base_agent import AgentTask, AgentTaskResult, BaseAgent
from friday.agents.registry import AgentRegistry

__all__ = [
    "BaseAgent",
    "AgentTask",
    "AgentTaskResult",
    "AgentRegistry",
]
