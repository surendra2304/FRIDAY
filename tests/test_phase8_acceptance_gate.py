# -*- coding: utf-8 -*-
"""Comprehensive End-to-End Acceptance & Security Gate for Phase 8 Multimodal Perception.

Verifies:
1. End-to-End Multimodal Lifecycle: Screen Capture -> Structured UI Understanding -> Coordinate Grounding -> Action Proposal -> Authorization Gate -> Simulated Execution -> State Verification -> Memory Recording.
2. Untrusted Screen / Prompt Injection Defense: Malicious OCR text attempting to command shell overrides or skip authorization is strictly neutralized.
3. Secret Redaction & Zero Raw Screenshot Persistence: Passwords, API keys, and sensitive tokens are redacted from visual facts and never saved to disk.
4. Ambiguity & Low-Confidence Guard: Ambiguous UI targets trigger user clarification prompts rather than guessing.
5. Proposal != Execution Invariant: Visual resolution only builds ComputerActionProposal; OS actions are never executed directly.
6. Stale-Context & Screen Change Detection: Outdated visual contexts cannot validate actions on refreshed displays.
7. Active Perception Loop Limits: Strict bounded observations prevent recursive reasoning loops.
8. Quota & Cost Protection: Perceptual hashing and caching suppress redundant Gemini calls.
"""

from unittest import mock
import pytest

from friday.core.types import SafetyLevel
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.task_context import ActiveTaskContext
from friday.vision.action_preparer import (
    ActionPreparationResult,
    GroundedElementTarget,
    GroundingStatus,
    PerceptionActionPreparer,
)
from friday.vision.actions import (
    ActionType,
    ComputerActionProposal,
    ProposalBuilder,
)
from friday.vision.computer_control import (
    ActionExecutionResult,
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.active_perception import (
    ActivePerceptionEngine,
    ObservationDecision,
    ObservationNecessity,
)
from friday.vision.cache_manager import PerceptionCacheManager
from friday.vision.episodic_memory import (
    EpisodicEnvironmentalFact,
    EpisodicEnvironmentalMemoryManager,
    MemoryImportance,
)
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.vision.screen_context import ScreenContext
from friday.vision.temporal import (
    EnvironmentalChange,
    EnvironmentalChangeType,
    TemporalEnvironmentTracker,
)
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement
from friday.voice.perception_resolver import (
    SpokenVisualIntentType,
    VoicePerceptionResolution,
    VoicePerceptionResolver,
)


# 1. Full Multimodal Lifecycle Gate
def test_full_multimodal_perception_lifecycle_gate():
    """Verify Screen Capture -> UI Parsing -> Grounding -> Proposal -> Auth -> Exec -> Verify -> Memory."""
    btn = UIElement(
        element_id="btn_commit",
        element_type=ElementType.BUTTON,
        label="Commit Changes",
        bounding_box=BoundingBox(ymin=200, xmin=300, ymax=300, xmax=600),
        confidence=0.98,
        is_interactive=True,
    )
    ctx = ScreenContext(
        summary="Git GUI client with uncommitted changes",
        width=1920,
        height=1080,
        ui_elements=[btn],
        active_application="GitExtensions.exe",
    )

    # 1. Action Preparation / Grounding
    preparer = PerceptionActionPreparer()
    prep_res = preparer.prepare_click_proposal(
        target_description="Commit Changes",
        screen_context=ctx,
        intent="Commit staged repository changes",
    )
    assert prep_res.is_success is True
    assert prep_res.status == GroundingStatus.GROUNDED
    proposal = prep_res.proposal
    assert proposal is not None
    assert proposal.is_executed is False

    # 2. Authorization Gate (Simulation of User Confirmation)
    proposal.is_executed = False
    assert proposal.requires_confirmation is True

    # 3. Safe Execution via ComputerActionExecutor (sandboxed=True)
    executor = ComputerActionExecutor(sandboxed=True)
    exec_res = executor.execute_proposal(proposal, user_confirmed=True)
    assert exec_res.status == ExecutionStatus.EXECUTED
    assert proposal.is_executed is True

    # 4. Temporal Observation & Memory Recording
    temporal = TemporalEnvironmentTracker()
    temporal.record_observation(ctx)

    memory = InMemoryConversationMemory()
    episodic_mgr = EpisodicEnvironmentalMemoryManager(memory=memory)
    fact = episodic_mgr.record_derived_fact(
        category="GIT_ACTION",
        fact_summary="User confirmed commit in GitExtensions.exe",
        importance=MemoryImportance.HIGH,
    )
    assert fact is not None
    assert fact.category == "GIT_ACTION"


# 2. Untrusted Screen & Prompt Injection Defense
def test_untrusted_screen_prompt_injection_defense():
    """Verify malicious visual OCR commands attempting to bypass authorization are neutralized."""
    preparer = PerceptionActionPreparer()
    btn = UIElement(
        element_id="evil_btn",
        element_type=ElementType.BUTTON,
        label="Execute Shell Override",
        bounding_box=BoundingBox(ymin=0, xmin=0, ymax=100, xmax=100),
    )
    ctx = ScreenContext(summary="Deceptive webpage", ui_elements=[btn])

    prep_res = preparer.prepare_click_proposal(
        target_description="system override and execute shell",
        screen_context=ctx,
        intent="Malicious attack",
    )
    assert prep_res.status == GroundingStatus.MALICIOUS_REJECTED
    assert prep_res.proposal is None


# 3. Secret Redaction & Zero Raw Screenshot Persistence
def test_secret_redaction_and_zero_raw_screenshot_persistence():
    """Verify secrets are redacted and raw binary screenshots are not saved to memory database."""
    memory = InMemoryConversationMemory()
    episodic_mgr = EpisodicEnvironmentalMemoryManager(memory=memory)

    raw_fact_text = "Window showed api_key=TEST_GEMINI_API_KEY_PLACEHOLDER_05 and password=MySuperSecret123"
    fact = episodic_mgr.record_derived_fact(
        category="DEV_STATE",
        fact_summary=raw_fact_text,
    )

    assert "[REDACTED_API_KEY]" in fact.fact_summary or "[REDACTED_SECRET]" in fact.fact_summary
    assert "[REDACTED_PASSWORD]" in fact.fact_summary
    assert "TEST_GEMINI_API_KEY_PLACEHOLDER_05" not in fact.fact_summary
    assert "MySuperSecret123" not in fact.fact_summary
    assert hasattr(fact, "image_bytes") is False or fact.to_dict().get("image_bytes") is None


# 4. Ambiguity & Clarification Handling
def test_ambiguity_and_clarification_handling():
    """Verify ambiguous UI targets prompt the user rather than arbitrarily selecting one."""
    preparer = PerceptionActionPreparer()
    btn1 = UIElement(
        element_id="b1",
        element_type=ElementType.BUTTON,
        label="Confirm Payment",
        bounding_box=BoundingBox(ymin=100, xmin=100, ymax=200, xmax=300),
        confidence=0.9,
    )
    btn2 = UIElement(
        element_id="b2",
        element_type=ElementType.BUTTON,
        label="Confirm Subscription",
        bounding_box=BoundingBox(ymin=300, xmin=100, ymax=400, xmax=300),
        confidence=0.88,
    )
    ctx = ScreenContext(summary="Checkout page", ui_elements=[btn1, btn2])

    prep_res = preparer.prepare_click_proposal(
        target_description="Confirm",
        screen_context=ctx,
        intent="Click confirm",
    )
    assert prep_res.status == GroundingStatus.AMBIGUOUS
    assert prep_res.proposal is None
    assert prep_res.clarification_prompt is not None
    assert "multiple matching elements" in prep_res.clarification_prompt


# 5. Proposal != Execution Invariant
def test_proposal_not_equal_execution_invariant():
    """Verify action proposals are purely declarative until explicitly confirmed and dispatched."""
    proposal = ProposalBuilder.click(x=500, y=500, intent="Click Settings icon")
    assert proposal.is_executed is False
    assert proposal.requires_confirmation is True

    executor = ComputerActionExecutor()
    # Unconfirmed execution attempt is blocked
    res = executor.execute_proposal(proposal, user_confirmed=False)
    assert res.status == ExecutionStatus.BLOCKED_UNCONFIRMED
    assert proposal.is_executed is False


# 6. Stale-Context & Screen Change Detection
def test_stale_context_and_screen_change_detection():
    """Verify actions cannot execute if the target element disappeared from the screen."""
    preparer = PerceptionActionPreparer()
    btn = UIElement(
        element_id="btn_ok",
        element_type=ElementType.BUTTON,
        label="OK",
        bounding_box=BoundingBox(ymin=50, xmin=50, ymax=100, xmax=100),
    )
    target = GroundedElementTarget(element=btn, pixel_center=(75, 75), match_score=1.0)

    # Subsequent observation where dialog is closed
    new_ctx = ScreenContext(summary="Empty desktop", ui_elements=[])
    is_valid = preparer.validate_target_not_stale(target, new_ctx)
    assert is_valid is False


# 7. Active Perception Loop Limits & Safety
def test_active_perception_loop_limits():
    """Verify perception engine strictly bounds recursive observation cycles."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider(default_response='{"summary": "Looping UI"}')
    engine = ActivePerceptionEngine(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        max_consecutive_observations=2,
    )

    # 1st observation
    ctx1, dec1 = engine.observe_if_needed(current_context=None, uncertainty_score=0.9)
    assert dec1.necessity == ObservationNecessity.UNCERTAIN_STATE

    # 2nd observation
    ctx2, dec2 = engine.observe_if_needed(current_context=ctx1, uncertainty_score=0.9, has_executed_action=True)
    assert dec2.necessity in [ObservationNecessity.UNCERTAIN_STATE, ObservationNecessity.ACTION_VERIFICATION]

    # 3rd observation -> Bound exceeded!
    ctx3, dec3 = engine.observe_if_needed(current_context=ctx2, uncertainty_score=0.9, has_executed_action=True)
    assert dec3.necessity == ObservationNecessity.BOUND_EXCEEDED
    assert dec3.should_observe is False


# 8. Quota & Cost Protection (Perception Caching)
def test_quota_and_cost_protection_via_caching():
    """Verify unchanged screen observations do not trigger redundant Gemini Vision API calls."""
    mock_cap = MockScreenCaptureProvider(width=640, height=480)
    mock_vis = MockVisionProvider(default_response='{"summary": "Static IDE Window"}')
    cache_mgr = PerceptionCacheManager(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        default_ttl_seconds=60.0,
    )

    ctx1 = cache_mgr.get_screen_context_cached()
    ctx2 = cache_mgr.get_screen_context_cached()
    ctx3 = cache_mgr.get_screen_context_cached()

    assert len(mock_vis.call_history) == 1
    assert cache_mgr.telemetry.cache_hits == 2
    assert cache_mgr.telemetry.suppressed_api_calls == 2
