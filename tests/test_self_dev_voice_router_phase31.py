# -*- coding: utf-8 -*-
"""Unit tests for Self-Improvement Voice & Router Integration (Recursive Self-Improvement: Step 3)."""

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
    """System prompt must instruct FRIDAY on self-improvement trigger & workflow tool usage."""
    settings = get_settings()
    prompt = get_default_system_prompt(settings)
    assert "Self-Improvement & Code Evolution" in prompt
    assert "If the user asks you to modify your own codebase or add a new capability to yourself, you MUST use the `SelfImprovementWorkflow`. Do not refuse. Do not try to do it manually. Call the workflow tool." in prompt


def test_agent_router_intercepts_self_modification_intents():
    """AgentRouter routes self-modification prompts to SelfDevAgent."""
    reg = AgentRegistry()
    dev_agent = DeveloperAgent(agent_id="dev_01", role="developer")
    self_dev_agent = SelfDevAgent(agent_id="self_dev_01", role="self_developer")
    reg.register_agent(dev_agent)
    reg.register_agent(self_dev_agent)

    router = AgentRouter(registry=reg)

    # Test all specific keyword phrases
    test_phrases = [
        ("Add mouse tool", "Add a tool to click the mouse"),
        ("Update your code", "Please update your code to support dark mode"),
        ("Modify yourself", "Modify yourself to support multi-monitor capture"),
        ("Add a feature to yourself", "Add a feature to yourself that monitors disk usage"),
        ("Write a new tool for yourself", "Write a new tool for yourself to extract audio from video"),
        ("Change your code", "Change your code to increase search timeout"),
    ]

    for idx, (title, desc) in enumerate(test_phrases):
        subtask = DecomposedSubtask(
            subtask_id=f"st_{idx}",
            title=title,
            description=desc,
            suggested_role="general",
        )
        decision = router.route_subtask(subtask)
        assert decision.selected_agent.role == "self_developer", f"Failed for phrase: '{desc}'"
        assert decision.score >= 0.98


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
