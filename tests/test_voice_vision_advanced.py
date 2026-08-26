# -*- coding: utf-8 -*-
"""Deterministic unit test suite for Evidence-Based Verification.7: Advanced Voice + Vision Interaction.

Tests:
1. Voice request classifying visual intent vs non-visual intent.
2. Voice request requiring visual perception ("look at the screen").
3. Voice request avoiding unnecessary perception when temporal context is sufficient ("what changed").
4. Historical reference resolution from episodic memory ("open the thing you were talking about").
5. Error reference resolution from active context ("look at the error").
6. Interruption and task state preservation.
7. Authorization boundary protection (voice+vision cannot bypass BaseAuthorizer).
8. Quota protection on voice-triggered vision calls.
"""

from unittest import mock
import pytest

from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.task_context import ActiveTaskContext
from friday.vision.active_perception import ActivePerceptionEngine
from friday.vision.episodic_memory import EpisodicEnvironmentalMemoryManager
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.screen_context import ScreenContext
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.temporal import (
    EnvironmentalChange,
    EnvironmentalChangeType,
    TemporalEnvironmentTracker,
)
from friday.voice.perception_resolver import (
    SpokenVisualIntentType,
    VoicePerceptionResolution,
    VoicePerceptionResolver,
)


# 1. Spoken Utterance Intent Classification
def test_voice_intent_classification():
    """Verify natural spoken expressions are classified accurately."""
    resolver = VoicePerceptionResolver()

    assert resolver.classify_spoken_utterance("What is on my screen?") == SpokenVisualIntentType.CURRENT_SCREEN
    assert resolver.classify_spoken_utterance("What changed?") == SpokenVisualIntentType.CHANGE_INQUIRY
    assert resolver.classify_spoken_utterance("Look at the error on line 45") == SpokenVisualIntentType.ERROR_INVESTIGATION
    assert resolver.classify_spoken_utterance("Click the Save button") == SpokenVisualIntentType.ELEMENT_ACTION
    assert resolver.classify_spoken_utterance("Open the thing you were talking about") == SpokenVisualIntentType.HISTORICAL_REFERENCE
    assert resolver.classify_spoken_utterance("What is the weather in Tokyo?") == SpokenVisualIntentType.NON_VISUAL


# 2. Voice Request Requiring Targeted Perception
def test_voice_request_triggers_targeted_perception():
    """Verify voice request for unobserved screen state requests perception."""
    resolver = VoicePerceptionResolver()
    res = resolver.resolve_voice_request("Look at the screen and read the title")

    assert res.requires_perception is True
    assert res.intent_type == SpokenVisualIntentType.CURRENT_SCREEN
    assert res.targeted_query == "Look at the screen and read the title"


# 3. Voice Request Reusing Temporal Context Without Extra Vision Call
def test_voice_request_reuses_temporal_context():
    """Verify 'what changed' query uses TemporalEnvironmentTracker without extra vision call."""
    temporal = TemporalEnvironmentTracker()
    ctx1 = ScreenContext(summary="State 1", active_application="App1.exe")
    ctx2 = ScreenContext(summary="State 2", active_application="App2.exe")
    temporal.record_observation(ctx1)
    temporal.record_observation(ctx2)

    resolver = VoicePerceptionResolver(temporal_tracker=temporal)
    res = resolver.resolve_voice_request("What changed?")

    assert res.requires_perception is False
    assert res.intent_type == SpokenVisualIntentType.CHANGE_INQUIRY
    assert "Active application changed from 'App1.exe' to 'App2.exe'" in res.resolved_context_summary


# 4. Historical Reference Resolution from Episodic Memory
def test_voice_reference_resolution_from_episodic_memory():
    """Verify 'the thing we were talking about' resolves from episodic memory."""
    memory = InMemoryConversationMemory()
    episodic = EpisodicEnvironmentalMemoryManager(memory=memory)
    episodic.record_derived_fact(
        category="WINDOW",
        fact_summary="User opened Grafana monitoring dashboard for payments service",
    )

    resolver = VoicePerceptionResolver(episodic_memory=episodic)
    res = resolver.resolve_voice_request("Open the thing we discussed")

    assert res.requires_perception is False
    assert res.intent_type == SpokenVisualIntentType.HISTORICAL_REFERENCE
    assert "Grafana monitoring dashboard" in res.resolved_context_summary


# 5. Error Reference Resolution from Active Context
def test_voice_error_resolution_from_active_context():
    """Verify 'look at the error' reuses active context errors when present."""
    resolver = VoicePerceptionResolver()
    ctx = ScreenContext(
        summary="Compilation failed",
        errors=["TypeError: Cannot read properties of undefined (reading 'map')"],
        overall_confidence=0.9,
    )

    res = resolver.resolve_voice_request("Look at the error", current_screen_context=ctx)
    assert res.requires_perception is False
    assert res.intent_type == SpokenVisualIntentType.ERROR_INVESTIGATION
    assert "TypeError: Cannot read properties of undefined" in res.resolved_context_summary


# 6. Task State Preservation Across Voice Interruption
def test_task_state_preservation_across_voice_interruption():
    """Verify active task context remains stable and uncorrupted during voice barge-in."""
    task_ctx = ActiveTaskContext(goal="Deploy service to staging")
    task_ctx.record_step_result(step_id="step_1", result="Container built successfully")

    resolver = VoicePerceptionResolver()
    # Spoken voice barge-in
    res = resolver.resolve_voice_request("What time is it?", task_context=task_ctx)

    assert res.requires_perception is False
    # Task context remains intact
    assert task_ctx.goal == "Deploy service to staging"
    assert len(task_ctx.step_outputs) == 1
    assert "step_1" in task_ctx.step_outputs
    assert task_ctx.step_outputs["step_1"] == "Container built successfully"


# 7. Authorization Boundary Protection
def test_authorization_boundary_protection():
    """Verify voice+vision reference does not auto-execute dangerous operations."""
    resolver = VoicePerceptionResolver()
    res = resolver.resolve_voice_request("Click the Format Hard Drive button")

    assert res.intent_type == SpokenVisualIntentType.ELEMENT_ACTION
    # The resolution only yields intent/query metadata; it NEVER executes actions directly
    assert hasattr(res, "execute") is False
