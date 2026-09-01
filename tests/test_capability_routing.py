"""Comprehensive Capability Routing Layer Test Suite.

Test Type: UNIT / PERFORMANCE / SECURITY

Validates:
1. Direct reasoning preference for pure conversational / factual queries.
2. Local computation preference for arithmetic and timestamps.
3. Memory retrieval preference for recall and past context queries.
4. Cached perception preference over repeated vision API calls on static screens.
5. External vision model routing only when screen state has changed or cache is missing.
6. Explicit cost, latency, confidence, and safety risk evaluation.
7. External API call avoidance tracking and cost savings computation.
"""

import pytest

# Explicit test markers
pytestmark = [pytest.mark.unit, pytest.mark.performance]

from friday.core.types import SafetyLevel
from friday.routing.capability_router import (
    CapabilityMetadata,
    CapabilityRouter,
    ExecutionCapabilityType,
)

# ============================================================================
# 1. Direct Reasoning Preference (0 External Calls)
# ============================================================================

def test_direct_reasoning_for_conversational_questions():
    """Verify conversational queries route directly without tool execution or vision."""
    router = CapabilityRouter()

    decision = router.route_request("Hello FRIDAY, how are you today?")

    assert decision.selected_capability == ExecutionCapabilityType.DIRECT_REASONING
    assert decision.avoided_external_call is True


# ============================================================================
# 2. Local Computation Preference
# ============================================================================

def test_local_computation_for_math_and_time():
    """Verify basic calculations and timestamp requests route to local deterministic computation."""
    router = CapabilityRouter()

    decision_math = router.route_request("What is 2 + 2?")
    assert decision_math.selected_capability == ExecutionCapabilityType.LOCAL_COMPUTATION
    assert decision_math.avoided_external_call is True

    decision_time = router.route_request("What time is it right now?")
    assert decision_time.selected_capability == ExecutionCapabilityType.LOCAL_COMPUTATION
    assert decision_time.avoided_external_call is True


# ============================================================================
# 3. Memory Retrieval Preference
# ============================================================================

def test_memory_retrieval_for_context_recall():
    """Verify past discussion recall routes to local memory search."""
    router = CapabilityRouter()

    decision = router.route_request("What did we talk about earlier yesterday?")

    assert decision.selected_capability == ExecutionCapabilityType.MEMORY_RETRIEVAL
    assert decision.avoided_external_call is True


# ============================================================================
# 4. Cached Screen vs Vision Model Routing
# ============================================================================

def test_cached_perception_preferred_when_screen_unchanged():
    """Verify unchanged screen reuses local cache and avoids external vision API calls."""
    router = CapabilityRouter(default_vision_cost_usd=0.002)

    context = {
        "cached_screen_observation": {"summary": "Active IDE"},
        "screen_unchanged": True,
        "cache_age_seconds": 1.5,
    }

    decision = router.route_request("Find the submit button on the screen", context=context)

    assert decision.selected_capability == ExecutionCapabilityType.LOCAL_SCREEN_INSPECTION
    assert decision.avoided_external_call is True
    assert decision.estimated_savings_usd == 0.002


def test_vision_model_invoked_when_screen_changed_or_uncached():
    """Verify changed screen or missing cache correctly invokes the external vision model."""
    router = CapabilityRouter(default_vision_cost_usd=0.002)

    context = {
        "cached_screen_observation": None,
        "screen_unchanged": False,
    }

    decision = router.route_request("Look at the screen and analyze what changed", context=context)

    assert decision.selected_capability == ExecutionCapabilityType.VISION_MODEL
    assert decision.avoided_external_call is False


# ============================================================================
# 5. Background Task Routing
# ============================================================================

def test_background_task_routing():
    """Verify asynchronous long running tasks route to BACKGROUND_TASK capability."""
    router = CapabilityRouter()

    decision = router.route_request("Monitor the build in the background and notify when done")

    assert decision.selected_capability == ExecutionCapabilityType.BACKGROUND_TASK


# ============================================================================
# 6. Scoring Telemetry & Risk Bounds
# ============================================================================

def test_capability_metadata_score_calculation():
    """Verify cost, latency, confidence, and risk score ordering."""
    local_meta = CapabilityMetadata(
        capability_type=ExecutionCapabilityType.LOCAL_COMPUTATION,
        estimated_cost_usd=0.0,
        estimated_latency_ms=1.0,
        confidence=1.0,
        risk_level=SafetyLevel.SAFE,
        is_local_deterministic=True,
    )

    external_meta = CapabilityMetadata(
        capability_type=ExecutionCapabilityType.VISION_MODEL,
        estimated_cost_usd=0.005,
        estimated_latency_ms=1000.0,
        confidence=0.85,
        risk_level=SafetyLevel.SAFE,
        is_local_deterministic=False,
    )

    # Local deterministic score must be strictly lower (better) than external API call
    assert local_meta.compute_selection_score() < external_meta.compute_selection_score()
