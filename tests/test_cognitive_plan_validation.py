# -*- coding: utf-8 -*-
"""Unit tests for CognitiveIntelligenceEngine plan validation."""

import pytest

from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.planning.types import TaskGraph, TaskStep, TaskDataType
from friday.core.types import SafetyLevel


def test_valid_plan_passes_check():
    """Verify valid sequential plan passes CHECK_PLAN phase."""
    engine = CognitiveIntelligenceEngine()

    step1 = TaskStep(id="step_1", tool_name="calculator", description="Add numbers")
    step2 = TaskStep(id="step_2", tool_name="time_date", description="Check date", dependencies=["step_1"])

    graph = TaskGraph(goal="Add numbers and check date", tasks=[step1, step2])
    decision = engine.check_plan_safety_and_confidence(graph)

    assert decision.plan_unsafe is False
    assert decision.should_continue_autonomously is True
    assert decision.current_phase == CognitivePhase.EXECUTE


def test_cyclic_plan_fails_check():
    """Verify cyclic plan is flagged unsafe during CHECK_PLAN."""
    engine = CognitiveIntelligenceEngine()

    step1 = TaskStep(id="step_1", tool_name="calculator", description="Add", dependencies=["step_2"])
    step2 = TaskStep(id="step_2", tool_name="time_date", description="Check", dependencies=["step_1"])

    # Bypassing initial validation if any
    graph = TaskGraph.__new__(TaskGraph)
    graph.tasks = {"step_1": step1, "step_2": step2}

    decision = engine.check_plan_safety_and_confidence(graph)

    assert decision.plan_unsafe is True
    assert decision.should_continue_autonomously is False
    assert "Cyclic dependency" in decision.explanation


def test_dangling_dependency_fails_check():
    """Verify missing dependency is flagged during CHECK_PLAN."""
    engine = CognitiveIntelligenceEngine()

    step1 = TaskStep(id="step_1", tool_name="calculator", description="Add", dependencies=["nonexistent_step"])
    graph = TaskGraph.__new__(TaskGraph)
    graph.tasks = {"step_1": step1}

    decision = engine.check_plan_safety_and_confidence(graph)

    assert decision.plan_unsafe is True
    assert decision.should_continue_autonomously is False
    assert "nonexistent" in decision.explanation
