"""Inference-backed FRIDAY goal planning stays bounded and safely validated."""

from __future__ import annotations

import pytest

from friday.autonomous.enhanced_controller import EnhancedAutonomousController


class PlannedController(EnhancedAutonomousController):
    def __init__(self, proposal):
        super().__init__()
        self.proposal = proposal
        self.requested_goal = None

    async def _request_inference_plan(self, goal: str):
        self.requested_goal = goal
        return self.proposal


@pytest.mark.asyncio
async def test_inference_plan_routes_market_work_through_intelx_futuris_stratex():
    controller = PlannedController(
        """
        {
          "steps": [
            {"id": "news", "agent": "IntelX", "task": "Research the latest market news.", "depends_on": []},
            {"id": "forecast", "agent": "Futuris", "task": "Forecast market scenarios from the research.", "depends_on": ["news"]},
            {"id": "trading", "agent": "Stratex", "task": "Review trade opportunities and risk against the forecast.", "depends_on": ["forecast"]}
          ]
        }
        """
    )

    plan = await controller.plan_goal("Analyze the market news and tell me the likely direction.")

    assert controller.requested_goal == "Analyze the market news and tell me the likely direction."
    assert [step.agent for step in plan.subtasks] == ["INTELX", "FUTURIS", "STRATEX"]
    assert plan.subtasks[1].dependencies == ["st_1"]
    assert plan.subtasks[2].dependencies == ["st_2"]
    assert plan.status == "PENDING"


@pytest.mark.asyncio
async def test_unknown_agent_discards_model_plan_and_uses_existing_fallback():
    controller = PlannedController(
        {"steps": [{"id": "work", "agent": "unknown-agent", "task": "Do work.", "depends_on": []}]}
    )

    plan = await controller.plan_goal("Build a small website.")

    assert plan.subtasks
    assert all(step.agent in {"FORGE", "SENTINEL"} for step in plan.subtasks)
    assert controller.active_plan_id == plan.plan_id


@pytest.mark.asyncio
async def test_cyclic_model_plan_is_rejected_before_any_step_can_run():
    controller = PlannedController(
        {
            "steps": [
                {"id": "first", "agent": "intelx", "task": "Research the topic.", "depends_on": ["second"]},
                {"id": "second", "agent": "futuris", "task": "Forecast from research.", "depends_on": ["first"]},
            ]
        }
    )

    plan = await controller.plan_goal("Forecast market developments.")

    assert plan.subtasks
    assert plan.plan_id in controller.plans
    assert all(step.status == "PENDING" for step in plan.subtasks)


@pytest.mark.asyncio
async def test_malformed_inference_response_falls_back_instead_of_stranding_goal():
    controller = PlannedController("I cannot produce a plan.")

    plan = await controller.plan_goal("Remember this project note.")

    assert len(plan.subtasks) == 2
    assert all(step.agent == "MEMORA" for step in plan.subtasks)
