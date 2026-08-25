# -*- coding: utf-8 -*-
"""Unit tests for Self-Improvement Voice & Router Integration (Phase 31: Step 3)."""

from unittest import mock
import pytest

from friday.agents.decomposer import DecomposedSubtask
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.agents.specialists.developer_agent import DeveloperAgent
from friday.agents.specialists.self_dev_agent import SelfDevAgent
from friday.agent.prompts import get_default_system_prompt
from friday.core.config import get_settings


def test_system_prompt_includes_self_improvement_rule():
    """System prompt must instruct FRIDAY on self-improvement trigger & confirmation."""
    settings = get_settings()
    prompt = get_default_system_prompt(settings)
    assert "Self-Improvement & Code Evolution" in prompt
    assert "If the user asks you to modify yourself, add a new tool, or change your own code" in prompt
    assert "Confirm the plan with the user first" in prompt


def test_agent_router_intercepts_self_modification_intents():
    """AgentRouter routes self-modification prompts to SelfDevAgent."""
    reg = AgentRegistry()
    dev_agent = DeveloperAgent(agent_id="dev_01", role="developer")
    self_dev_agent = SelfDevAgent(agent_id="self_dev_01", role="self_developer")
    reg.register_agent(dev_agent)
    reg.register_agent(self_dev_agent)

    router = AgentRouter(registry=reg)

    subtask1 = DecomposedSubtask(
        subtask_id="st_01",
        title="Add mouse click tool",
        description="Add a tool to click the mouse",
        suggested_role="general",
    )
    decision1 = router.route_subtask(subtask1)
    assert decision1.selected_agent.role == "self_developer"
    assert decision1.score >= 0.9

    subtask2 = DecomposedSubtask(
        subtask_id="st_02",
        title="Update codebase",
        description="Modify yourself to support multi-monitor capture",
        suggested_role="developer",
    )
    decision2 = router.route_subtask(subtask2)
    assert decision2.selected_agent.role == "self_developer"

    subtask3 = DecomposedSubtask(
        subtask_id="st_03",
        title="Change your code",
        description="Change your code to increase search timeout",
        suggested_role="coder",
    )
    decision3 = router.route_subtask(subtask3)
    assert decision3.selected_agent.role == "self_developer"


def test_agent_router_normal_dev_issue_routes_to_dev_agent():
    """Normal bug fix requests route to developer agent when not self-modifying."""
    reg = AgentRegistry()
    dev_agent = DeveloperAgent(agent_id="dev_01", role="developer")
    self_dev_agent = SelfDevAgent(agent_id="self_dev_01", role="self_developer")
    reg.register_agent(dev_agent)
    reg.register_agent(self_dev_agent)

    router = AgentRouter(registry=reg)

    subtask = DecomposedSubtask(
        subtask_id="st_04",
        title="Fix issue #4",
        description="Resolve database connection leak in external service",
        suggested_role="developer",
    )
    decision = router.route_subtask(subtask)
    assert decision.selected_agent.role == "developer"
