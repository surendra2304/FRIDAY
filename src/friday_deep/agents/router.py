from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from ..contracts import AgentCapability, PlanNode


@dataclass(frozen=True)
class Performance:
    success_rate: float = 0.0
    avg_latency_ms: float = 10000.0
    failure_rate: float = 1.0
    samples: int = 0


@dataclass(frozen=True)
class RoutingDecision:
    task_id: str
    agent: AgentCapability
    score: float
    reasons: tuple[str, ...]


class AgentRouter:
    def __init__(self, agents, performance=None):
        self.agents = list(agents)
        self.performance = performance or {}

    def route(self, task: PlanNode) -> RoutingDecision:
        candidates = []
        for a in self.agents:
            if task.tool_name and not a.can_use(task.tool_name):
                continue
            score = 0.0
            reasons = []
            if task.role.lower() == a.role.lower():
                score += 0.55
                reasons.append("exact role")
            elif task.role.lower() in a.role.lower():
                score += 0.25
                reasons.append("partial role")
            if task.tool_name:
                score += 0.3
                reasons.append("tool scope")
            hits = sum(1 for s in a.skills if s.lower() in (task.title + " " + task.description).lower())
            score += min(0.1, hits * 0.02)
            p = self.performance.get(a.agent_id)
            if p and p.samples:
                score += max(0, min(1, p.success_rate)) * 0.12
                score += max(-0.05, min(0.08, (2000 - p.avg_latency_ms) / 25000))
                score -= max(0, min(0.12, p.failure_rate * 0.12))
                reasons.append(f"reliability {p.success_rate:.2f}")
            if isfinite(score):
                candidates.append((max(0, min(1, score)), a, reasons))
        if not candidates:
            raise ValueError(f"No capable agent for {task.node_id}")
        candidates.sort(key=lambda x: (-x[0], x[1].agent_id))
        s, a, r = candidates[0]
        return RoutingDecision(task.node_id, a, round(s, 4), tuple(r))
