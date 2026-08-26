# -*- coding: utf-8 -*-
"""Agent Router for FRIDAY Phase 13 Multi-Agent System.

Scores candidates from the Agent Registry based on role alignment, capabilities,
and tool availability, then selects the best specialist agent for a subtask.
"""

from dataclasses import dataclass
import re
from typing import Any, List, Optional, Tuple

from friday.agents.base_agent import BaseAgent
from friday.agents.decomposer import DecomposedSubtask
from friday.agents.registry import AgentRegistry
from friday.core.logging import get_logger

logger = get_logger("agents.router")


@dataclass
class AgentRoutingDecision:
    """Selected agent and match score for a given subtask."""
    subtask_id: str
    selected_agent: BaseAgent
    score: float
    rationale: str


class AgentRouter:
    """Matches subtasks to the most capable registered specialist agent."""

    def __init__(
        self,
        registry: AgentRegistry,
        default_agent: Optional[BaseAgent] = None,
        memory: Optional[Any] = None,
        skill_registry: Optional[Any] = None,
    ) -> None:
        self.registry = registry
        self.default_agent = default_agent
        self.memory = memory
        if skill_registry is None:
            try:
                from friday.skills.registry import skill_registry as default_skill_reg
                self.skill_registry = default_skill_reg
            except Exception:
                self.skill_registry = None
        else:
            self.skill_registry = skill_registry

    def find_matching_skill(self, user_request: str, threshold: float = 0.80) -> Optional[Tuple[Any, float]]:
        """Look up if user request directly activates an installed Skill."""
        if self.skill_registry:
            return self.skill_registry.find_matching_skill(user_request, threshold=threshold)
        return None

    def route_subtask(self, subtask: DecomposedSubtask) -> AgentRoutingDecision:
        """Score available agents and return the best match for the subtask."""
        agents = self.registry.list_agents()
        if not agents:
            if self.default_agent:
                return AgentRoutingDecision(
                    subtask_id=subtask.subtask_id,
                    selected_agent=self.default_agent,
                    score=1.0,
                    rationale="Default fallback agent used (registry empty).",
                )
            raise ValueError("No agents registered and no default agent configured in AgentRouter.")

        suggested = subtask.suggested_role.lower().strip()
        description = (subtask.description or "").lower()

        # High-priority keyword matching for self-modification / self-improvement requests:
        # Bypasses GeneralAgent and routes directly to SelfDevAgent
        text_to_check = f"{subtask.title or ''} {subtask.description or ''} {subtask.suggested_role or ''}".lower()
        self_mod_patterns = [
            r"\badd\s+(?:a\s+)?tool\b",
            r"\bupdate\s+(?:your\s+)?code\b",
            r"\bmodify\s+yourself\b",
            r"\badd\s+(?:a\s+)?feature\s+(?:to|for)\s+yourself\b",
            r"\bwrite\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\b",
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\b",
            r"\bbuild\s+(?:a\s+)?(?:new\s+)?tool\s+(?:to|for)\s+yourself\b",
            r"\bchange\s+your\s+code\b",
            r"\bmodify\s+your\s+code\b",
            r"\bself[\s\-_]improv(?:e|ement)\b",
            r"\bself[\s\-_]dev\b",
        ]
        if any(re.search(pat, text_to_check) for pat in self_mod_patterns):
            self_dev = self.registry.get_agent("self_developer") or self.registry.get_agent("developer")
            if self_dev:
                return AgentRoutingDecision(
                    subtask_id=subtask.subtask_id,
                    selected_agent=self_dev,
                    score=0.98,
                    rationale="Self-modification intent detected; routed directly to SelfDevAgent.",
                )

        best_agent: Optional[BaseAgent] = None
        best_score: float = -1.0
        best_rationale: str = ""

        for agent in agents:
            score = 0.0
            rationale_parts: List[str] = []

            # 1. Direct role match
            agent_role = agent.role.lower().strip()
            if agent_role == suggested:
                score += 0.6
                rationale_parts.append(f"Direct role match '{agent.role}' (+0.6)")
            elif suggested in agent_role or agent_role in suggested:
                score += 0.4
                rationale_parts.append(f"Partial role match '{agent.role}' (+0.4)")

            # 2. Instruction / keyword alignment
            agent_instructions = agent.instructions.lower()
            matching_words = [w for w in suggested.split() if len(w) > 3 and w in agent_instructions]
            if matching_words:
                score += 0.2
                rationale_parts.append(f"Instruction keyword overlap ({len(matching_words)}) (+0.2)")

            # 3. Tool coverage alignment
            if agent.allowed_tools:
                score += 0.1
                rationale_parts.append("Has specialized allowed tools (+0.1)")
            else:
                score += 0.05
                rationale_parts.append("Has full tool access (+0.05)")

            # 4. Dynamic routing via Lab Experiment performance history
            if self.memory is not None and hasattr(self.memory, "get_provider_performance_stats"):
                try:
                    stats = self.memory.get_provider_performance_stats(task_type=subtask.suggested_role)
                    if not stats:
                        stats = self.memory.get_provider_performance_stats()
                    for s in stats:
                        model_match = agent.preferred_models and s["model_name"] in agent.preferred_models
                        provider_match = s["provider_name"] == getattr(agent.llm, "provider_name", "")
                        if model_match or provider_match:
                            bonus = min(0.2, (s["success_rate"] * 0.15) + (max(0.0, 500.0 - s["avg_latency_ms"]) / 5000.0))
                            score += bonus
                            rationale_parts.append(f"Historical experiment score bonus (+{bonus:.2f})")
                except Exception as ex:
                    logger.debug(f"Could not load experiment stats in router: {ex}")

            if score > best_score:
                best_score = score
                best_agent = agent
                best_rationale = "; ".join(rationale_parts)

        # Fallback to general agent or first available if no score advantage
        if not best_agent or best_score < 0.1:
            general = self.registry.get_agent("general") or agents[0]
            return AgentRoutingDecision(
                subtask_id=subtask.subtask_id,
                selected_agent=general,
                score=0.1,
                rationale=f"Fallback to general agent '{general.role}'.",
            )

        return AgentRoutingDecision(
            subtask_id=subtask.subtask_id,
            selected_agent=best_agent,
            score=round(best_score, 3),
            rationale=best_rationale,
        )
