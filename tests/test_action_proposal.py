# -*- coding: utf-8 -*-
"""Deterministic unit tests for Phase 6.7 Computer Action Proposal Layer & Safety Gating."""

import pytest

from friday.core.types import SafetyLevel
from friday.agent.agent import FridayAgent
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.tools.builtin.action_proposal import ProposeComputerActionTool


def test_proposal_builder_click_and_type():
    """Verify ProposalBuilder creates isolated proposals with strict confirmation flags."""
    click_prop = ProposalBuilder.click(x=450, y=320, intent="Click Submit Button")
    assert click_prop.action_type == ActionType.CLICK
    assert click_prop.arguments == {"x": 450, "y": 320}
    assert click_prop.intent == "Click Submit Button"
    assert click_prop.risk_level == SafetyLevel.SENSITIVE
    assert click_prop.requires_confirmation is True
    assert click_prop.is_executed is False  # Propose != Execute

    type_prop = ProposalBuilder.type_text(text="print('Hello World')", intent="Type python code in editor")
    assert type_prop.action_type == ActionType.TYPE
    assert type_prop.arguments["text"] == "print('Hello World')"
    assert type_prop.risk_level == SafetyLevel.SENSITIVE
    assert type_prop.requires_confirmation is True
    assert type_prop.is_executed is False


def test_proposal_builder_dangerous_actions_automatic_risk_elevation():
    """Verify high-risk commands and hotkeys are automatically classified as DANGEROUS."""
    del_prop = ProposalBuilder.type_text(text="rm -rf /tmp/data", intent="Delete temp directory")
    assert del_prop.risk_level == SafetyLevel.DANGEROUS
    assert del_prop.requires_confirmation is True

    alt_f4_prop = ProposalBuilder.hotkey(keys=["Alt", "F4"], intent="Close active window")
    assert alt_f4_prop.risk_level == SafetyLevel.DANGEROUS
    assert alt_f4_prop.requires_confirmation is True


def test_propose_computer_action_tool_formulation():
    """Verify ProposeComputerActionTool formulates and returns proposal summary without OS side-effects."""
    tool = ProposeComputerActionTool()
    assert tool.name == "propose_computer_action"
    assert tool.safety_level == SafetyLevel.SAFE  # Formulating a proposal is safe

    res = tool.execute(
        action_type="click",
        intent="Click login button",
        x=500,
        y=400,
    )
    assert res.is_error is False
    assert "[ACTION PROPOSAL: CLICK]" in res.content
    assert "x=500, y=400" in res.content
    assert "PROPOSED (NOT EXECUTED)" in res.content

    assert tool.last_proposal is not None
    assert tool.last_proposal.is_executed is False


def test_agent_includes_propose_computer_action_tool():
    """Verify FridayAgent default registry includes propose_computer_action tool."""
    agent = FridayAgent()
    tool_names = [t.name for t in agent.tools.list_tools()]
    assert "propose_computer_action" in tool_names


def test_proposal_validation_missing_arguments():
    """Verify tool rejects invalid or missing coordinates/arguments gracefully."""
    tool = ProposeComputerActionTool()

    # Missing coordinates for click
    res1 = tool.execute(action_type="click", intent="Click somewhere")
    assert res1.is_error is True
    assert "Missing 'x' or 'y'" in res1.content

    # Missing text for typing
    res2 = tool.execute(action_type="type", intent="Type empty")
    assert res2.is_error is True
    assert "Missing 'text'" in res2.content
