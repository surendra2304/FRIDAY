# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Phase 8.8: Perception-Driven Safe Action Preparation.

Tests:
1. Exact target identification and coordinate grounding from BoundingBox to screen pixels.
2. Ambiguous target handling (requests clarification when multiple elements match).
3. Action proposal creation (generates ComputerActionProposal with Proposal != Execution).
4. Authorization gating (proposal requires confirmation before execution).
5. Malicious screen text defense (prevents untrusted screen text from generating executable actions).
6. Stale-screen detection (validates element is still present on refreshed screen).
7. Execution verification and safe failure handling.
"""

import pytest

from friday.core.types import SafetyLevel
from friday.vision.action_preparer import (
    ActionPreparationResult,
    GroundedElementTarget,
    GroundingStatus,
    PerceptionActionPreparer,
)
from friday.vision.actions import ActionType, ComputerActionProposal
from friday.vision.screen_context import ScreenContext
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement


# 1. Exact Target Identification and Coordinate Grounding
def test_exact_target_identification_and_grounding():
    """Verify target element is matched and normalized bounding box converted to pixel coordinates."""
    preparer = PerceptionActionPreparer()

    btn = UIElement(
        element_id="btn_save",
        element_type=ElementType.BUTTON,
        label="Save Changes",
        bounding_box=BoundingBox(ymin=100, xmin=200, ymax=200, xmax=400),
        confidence=0.95,
        is_interactive=True,
    )
    ctx = ScreenContext(
        summary="Settings window with Save Changes button",
        width=1920,
        height=1080,
        ui_elements=[btn],
    )

    res = preparer.prepare_click_proposal(
        target_description="Save Changes",
        screen_context=ctx,
        intent="Save application configuration",
    )

    assert res.is_success is True
    assert res.status == GroundingStatus.GROUNDED
    assert res.proposal is not None
    assert res.proposal.action_type == ActionType.CLICK
    # Center of [xmin=200, ymin=100, xmax=400, ymax=200] normalized is (300/1000 * 1920, 150/1000 * 1080) = (576, 162)
    assert res.proposal.arguments["x"] == 576
    assert res.proposal.arguments["y"] == 162
    assert res.proposal.is_executed is False  # Proposal != Execution


# 2. Ambiguous Target Handling
def test_ambiguous_target_handling():
    """Verify clarification is requested when multiple elements match target label."""
    preparer = PerceptionActionPreparer(ambiguity_margin=0.20)

    btn1 = UIElement(
        element_id="btn_del_1",
        element_type=ElementType.BUTTON,
        label="Delete Account",
        bounding_box=BoundingBox(ymin=100, xmin=100, ymax=150, xmax=300),
        confidence=0.95,
    )
    btn2 = UIElement(
        element_id="btn_del_2",
        element_type=ElementType.BUTTON,
        label="Delete Database",
        bounding_box=BoundingBox(ymin=200, xmin=100, ymax=250, xmax=300),
        confidence=0.92,
    )
    ctx = ScreenContext(
        summary="Danger zone settings",
        width=1920,
        height=1080,
        ui_elements=[btn1, btn2],
    )

    res = preparer.prepare_click_proposal(
        target_description="Delete",
        screen_context=ctx,
        intent="Perform deletion",
    )

    assert res.status == GroundingStatus.AMBIGUOUS
    assert res.is_success is False
    assert res.proposal is None
    assert res.clarification_prompt is not None
    assert "multiple matching elements" in res.clarification_prompt


# 3. Action Proposal Authorization Gating
def test_action_proposal_authorization_gating():
    """Verify generated proposal requires explicit user confirmation and has SENSITIVE/DANGEROUS risk."""
    preparer = PerceptionActionPreparer()
    btn = UIElement(
        element_id="btn_deploy",
        element_type=ElementType.BUTTON,
        label="Deploy",
        bounding_box=BoundingBox(ymin=300, xmin=300, ymax=400, xmax=500),
        confidence=0.90,
    )
    ctx = ScreenContext(summary="Deploy page", width=1000, height=1000, ui_elements=[btn])

    res = preparer.prepare_click_proposal("Deploy", ctx, intent="Deploy microservice")
    assert res.proposal.requires_confirmation is True
    assert res.proposal.risk_level in [SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS]


# 4. Malicious Visual Text Defense
def test_malicious_visual_text_defense():
    """Verify malicious instructions embedded in screen text are rejected."""
    preparer = PerceptionActionPreparer()
    btn = UIElement(
        element_id="btn_hack",
        element_type=ElementType.BUTTON,
        label="System Override",
        bounding_box=BoundingBox(ymin=0, xmin=0, ymax=100, xmax=100),
    )
    ctx = ScreenContext(summary="Malicious page", ui_elements=[btn])

    res = preparer.prepare_click_proposal(
        target_description="system override and execute shell",
        screen_context=ctx,
        intent="Malicious click",
    )
    assert res.status == GroundingStatus.MALICIOUS_REJECTED
    assert res.proposal is None


# 5. Stale-Screen Detection
def test_stale_screen_detection():
    """Verify target validation fails if element moved or disappeared on refreshed screen."""
    preparer = PerceptionActionPreparer()

    btn1 = UIElement(
        element_id="btn_1",
        element_type=ElementType.BUTTON,
        label="Submit",
        bounding_box=BoundingBox(ymin=100, xmin=100, ymax=200, xmax=200),
    )
    target = GroundedElementTarget(
        element=btn1,
        pixel_center=(288, 162),
        match_score=1.0,
    )

    # Refreshed screen where Submit button disappeared (e.g. dialog closed)
    refreshed_ctx = ScreenContext(
        summary="Success dialog without submit button",
        width=1920,
        height=1080,
        ui_elements=[],
    )

    is_valid = preparer.validate_target_not_stale(target, refreshed_ctx)
    assert is_valid is False


# 6. Low Confidence Target Handling
def test_low_confidence_target_handling():
    """Verify elements with confidence below threshold are flagged as LOW_CONFIDENCE."""
    preparer = PerceptionActionPreparer(min_confidence=0.85)

    btn = UIElement(
        element_id="btn_uncertain",
        element_type=ElementType.BUTTON,
        label="Uncertain Button",
        bounding_box=BoundingBox(ymin=0, xmin=0, ymax=100, xmax=100),
        confidence=0.60,
    )
    ctx = ScreenContext(summary="Fuzzy UI", ui_elements=[btn])

    res = preparer.prepare_click_proposal("Uncertain Button", ctx, intent="Click fuzzy button")
    assert res.status == GroundingStatus.LOW_CONFIDENCE
    assert res.proposal is None
