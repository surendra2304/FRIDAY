"""
FRIDAY/apps/core/src/friday_core/universe_cost_optimizer.py — FRIDAY Universe Cost Optimizer.

Cross-agent cost tracking, budget management, cost optimization,
resource allocation, and cost anomaly detection.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentCostRecord:
    """A cost record for an agent."""
    agent_name: str
    cost_category: str = "compute"  # compute, storage, network, API, memory
    amount: float = 0.0
    currency: str = "USD"
    timestamp: float = field(default_factory=time.time)
    description: str = ""


@dataclass
class BudgetLimit:
    """A budget limit for an agent."""
    agent_name: str
    monthly_budget: float = 0.0
    spent_this_month: float = 0.0
    category_limits: dict[str, float] = field(default_factory=dict)
    alert_threshold: float = 0.8


@dataclass
class CostOptimizationSuggestion:
    """A cost optimization suggestion."""
    suggestion_id: str
    agent_name: str
    category: str
    description: str
    estimated_savings: float = 0.0
    priority: str = "medium"  # low, medium, high
    effort: str = "low"  # low, medium, high


class UniverseCostOptimizer:
    """Engine for universe-wide cost optimization."""

    def __init__(self) -> None:
        self._records: list[AgentCostRecord] = []
        self._budgets: dict[str, BudgetLimit] = {}
        self._suggestions: list[CostOptimizationSuggestion] = []

    def set_budget(self, agent_name: str, monthly_budget: float,
                   category_limits: dict[str, float] | None = None,
                   alert_threshold: float = 0.8) -> BudgetLimit:
        """Set a budget limit for an agent."""
        budget = BudgetLimit(
            agent_name=agent_name, monthly_budget=monthly_budget,
            category_limits=category_limits or {}, alert_threshold=alert_threshold,
        )
        self._budgets[agent_name] = budget
        return budget

    def record_cost(self, agent_name: str, amount: float,
                    cost_category: str = "compute",
                    description: str = "") -> AgentCostRecord:
        """Record a cost."""
        record = AgentCostRecord(
            agent_name=agent_name, amount=amount,
            cost_category=cost_category, description=description,
        )
        self._records.append(record)
        budget = self._budgets.get(agent_name)
        if budget:
            budget.spent_this_month += amount
        return record

    def analyze_costs(self, agent_name: str) -> dict[str, Any]:
        """Analyze costs for an agent."""
        agent_records = [r for r in self._records if r.agent_name == agent_name]
        total_cost = sum(r.amount for r in agent_records)
        by_category = {}
        for r in agent_records:
            by_category[r.cost_category] = by_category.get(r.cost_category, 0) + r.amount

        budget = self._budgets.get(agent_name)
        budget_status = "not_set"
        if budget:
            budget_pct = budget.spent_this_month / max(0.01, budget.monthly_budget)
            if budget_pct > 1.0:
                budget_status = "over_budget"
            elif budget_pct > budget.alert_threshold:
                budget_status = "warning"
            else:
                budget_status = "ok"

        return {
            "agent_name": agent_name,
            "total_cost": round(total_cost, 2),
            "cost_count": len(agent_records),
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "budget_status": budget_status,
        }

    def generate_suggestions(self) -> list[CostOptimizationSuggestion]:
        """Generate cost optimization suggestions."""
        suggestions = []
        for agent_name in self._budgets:
            analysis = self.analyze_costs(agent_name)
            if analysis["budget_status"] == "over_budget":
                suggestions.append(CostOptimizationSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:12]}",
                    agent_name=agent_name, category="compute",
                    description=f"Agent {agent_name} is over budget. Reduce compute usage.",
                    estimated_savings=analysis["total_cost"] * 0.2,
                    priority="high", effort="medium",
                ))
        self._suggestions = suggestions
        return suggestions

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        total_cost = sum(r.amount for r in self._records)
        return {
            "total_cost": round(total_cost, 2),
            "total_records": len(self._records),
            "total_budgets": len(self._budgets),
            "total_suggestions": len(self._suggestions),
            "engine_status": "operational",
        }


engine = UniverseCostOptimizer()


@router.post("/cost/budgets")
async def set_budget(agent_name: str, monthly_budget: float,
                     category_limits: dict[str, float] | None = None,
                     alert_threshold: float = 0.8):
    """Set a budget limit."""
    budget = engine.set_budget(agent_name, monthly_budget, category_limits, alert_threshold)
    return {"agent_name": agent_name, "monthly_budget": budget.monthly_budget}


@router.post("/cost/records")
async def record_cost(agent_name: str, amount: float, cost_category: str = "compute",
                      description: str = ""):
    """Record a cost."""
    record = engine.record_cost(agent_name, amount, cost_category, description)
    return {"agent_name": agent_name, "amount": amount}


@router.get("/cost/analysis/{agent_name}")
async def analyze_costs(agent_name: str):
    """Analyze costs for an agent."""
    return engine.analyze_costs(agent_name)


@router.post("/cost/suggestions")
async def generate_suggestions():
    """Generate cost optimization suggestions."""
    suggestions = engine.generate_suggestions()
    return {
        "suggestion_count": len(suggestions),
        "suggestions": [
            {"agent": s.agent_name, "priority": s.priority, "estimated_savings": s.estimated_savings}
            for s in suggestions
        ],
    }


@router.get("/cost/report")
async def cost_report():
    """Get cost optimizer report."""
    return engine.get_report()
