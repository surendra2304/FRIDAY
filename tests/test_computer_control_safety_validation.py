# -*- coding: utf-8 -*-
"""Comprehensive Computer Control Safety and Real-Machine Validation Test Suite for Core Architecture & Types0.7.

Validates:
1. Proposal != Execution invariant.
2. Hard-block safety gates (passwords, credential extraction, payments, shell escapes, destructive commands).
3. Authorization requirement for benign interactive proposals.
4. Ambiguous element and low-confidence grounding detection.
5. Stale-screen and environmental shift detection before action execution.
6. Safe, reversible action gating under strict local policies.
"""

from unittest import mock
import pytest

from friday.agent.planner import PlanStep
from friday.agent.safety_gate import AutonomousSafetyGate, TaskRiskLevel
from friday.core.types import SafetyLevel
from friday.tools.registry import ToolRegistry
from friday.vision.action_preparer import (
    ActionPreparationResult,
    GroundedElementTarget,
    GroundingStatus,
    PerceptionActionPreparer,
)
from friday.vision.actions import ActionType, ComputerActionProposal
from friday.vision.screen_context import ScreenContext
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement


# --- 1. Hard-Block Safety Gate Validation ---

def test_hard_block_prohibited_actions():
    """Verify that dangerous, credential, financial, and destructive commands are BLOCKED."""
    registry = ToolRegistry()
    gate = AutonomousSafetyGate(tool_registry=registry)

    prohibited_proposals = [
        ("read .env file", "credential extraction"),
        ("rm -rf /root", "destructive filesystem deletion"),
        ("transfer funds via wire", "financial transaction"),
        ("dump credentials from memory", "private key theft"),
        ("format c: drive", "destructive disk formatting"),
        ("bypass auth checks", "security bypass"),
    ]

    for desc, reason in prohibited_proposals:
        step = PlanStep(step_id="step_hack", description=desc)
        risk = gate.classify_risk(step=step)
        assert risk == TaskRiskLevel.BLOCKED, f"Failed to block {reason}"


# --- 2. Proposal != Execution Invariant for Benign Computer Actions ---

def test_proposal_generation_requires_authorization():
    """Verify benign UI interactions produce structured proposals that require explicit user confirmation."""
    preparer = PerceptionActionPreparer()

    btn = UIElement(
        element_id="btn_refresh",
        element_type=ElementType.BUTTON,
        label="Refresh Window",
        bounding_box=BoundingBox(ymin=100, xmin=100, ymax=200, xmax=200),
        confidence=0.98,
        is_interactive=True,
    )
    ctx = ScreenContext(summary="Benign app", width=1920, height=1080, ui_elements=[btn])

    res = preparer.prepare_click_proposal(
        target_description="Refresh Window",
        screen_context=ctx,
        intent="Reload view",
    )

    assert res.is_success is True
    assert res.proposal is not None
    assert res.proposal.action_type == ActionType.CLICK
    assert res.proposal.requires_confirmation is True
    assert res.proposal.risk_level == SafetyLevel.SENSITIVE


# --- 3. Ambiguous and Low-Confidence Element Detection ---

def test_ambiguous_and_low_confidence_rejection():
    """Verify that multiple matching elements or low confidence elements abort proposal creation."""
    preparer = PerceptionActionPreparer(min_confidence=0.80)

    btn1 = UIElement(element_id="b1", element_type=ElementType.BUTTON, label="OK", bounding_box=BoundingBox(ymin=10, xmin=10, ymax=50, xmax=50), confidence=0.95)
    btn2 = UIElement(element_id="b2", element_type=ElementType.BUTTON, label="OK", bounding_box=BoundingBox(ymin=60, xmin=60, ymax=100, xmax=100), confidence=0.95)

    ctx_ambiguous = ScreenContext(summary="Dialog with two OK buttons", width=1920, height=1080, ui_elements=[btn1, btn2])

    res_ambiguous = preparer.prepare_click_proposal("OK", ctx_ambiguous, intent="Confirm action")
    assert res_ambiguous.status == GroundingStatus.AMBIGUOUS
    assert res_ambiguous.proposal is None

    # Low confidence
    btn_fuzzy = UIElement(element_id="b3", element_type=ElementType.BUTTON, label="Close", bounding_box=BoundingBox(ymin=0, xmin=0, ymax=10, xmax=10), confidence=0.45)
    ctx_fuzzy = ScreenContext(summary="Fuzzy close icon", width=1920, height=1080, ui_elements=[btn_fuzzy])

    res_fuzzy = preparer.prepare_click_proposal("Close", ctx_fuzzy, intent="Close dialog")
    assert res_fuzzy.status == GroundingStatus.LOW_CONFIDENCE
    assert res_fuzzy.proposal is None


# --- 4. Stale-Screen Detection and Execution Abort ---

def test_stale_screen_validation_aborts_execution():
    """Verify target element absence on refreshed screen halts execution."""
    preparer = PerceptionActionPreparer()

    btn = UIElement(element_id="btn_submit", element_type=ElementType.BUTTON, label="Submit", bounding_box=BoundingBox(ymin=100, xmin=100, ymax=200, xmax=200), confidence=0.95)
    target = GroundedElementTarget(element=btn, pixel_center=(288, 162), match_score=1.0)

    # Refreshed screen where button vanished
    refreshed_ctx = ScreenContext(summary="Submitted view", width=1920, height=1080, ui_elements=[])

    is_fresh = preparer.validate_target_not_stale(target, refreshed_ctx)
    assert is_fresh is False
