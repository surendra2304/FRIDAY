# -*- coding: utf-8 -*-
"""Verification tests for FRIDAY's Evidence-Based Bounded Recovery & False-Success Detection."""

import os
import json
import pytest
from unittest.mock import MagicMock

from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.verification import StepVerifier, VerificationResult, VerificationStatus
from friday.agent.recovery import AutonomousRecoveryManager, FailureAnalyzer, FailureType, RecoveryStrategy
from friday.agent.executor import TaskExecutionEngine
from friday.core.auth import AutoApproveAuthorizer
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class FalseSuccessFileTool(BaseTool):
    """A tool that claims it created a file, but actually fails to write to disk (simulating a silent failure / bug)."""
    name = "create_file"
    description = "Create a file on disk"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}

    def execute(self, path: str = "", **kwargs) -> ToolResult:
        # Deliberately do NOT write the file to simulate false-success
        return ToolResult(
            name=self.name,
            content=f"Successfully created file at {path}",
            is_error=False,
            safety_level=self.safety_level,
        )


class GenuineFileTool(BaseTool):
    """A tool that genuinely creates a file on disk."""
    name = "genuine_create_file"
    description = "Genuinely create a file on disk"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}

    def execute(self, path: str = "", content: str = "hello", **kwargs) -> ToolResult:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(
            name=self.name,
            content=f"Successfully written {len(content)} bytes to {path}",
            is_error=False,
            safety_level=self.safety_level,
        )


# ============================================================================
# 1. False-Success Tool Results vs Real-World Evidence Tests
# ============================================================================

def test_false_success_file_creation_rejected(tmp_path):
    """Verify that a tool claiming success is rejected when filesystem evidence shows file was not created."""
    fake_file = str(tmp_path / "non_existent_output.txt")
    step = PlanStep(
        step_id="step_file_1",
        description="Write output file",
        tool_name="create_file",
        parameters={"path": fake_file},
        evidence_source="filesystem",
        postconditions=[f"file_exists:{fake_file}"],
    )

    # Tool returned a cheerful success message
    tool_output = f"Successfully created file at {fake_file}"

    # StepVerifier must verify real filesystem state and detect false success
    vres = StepVerifier.verify_step_result(step, tool_output)

    assert not vres.passed
    assert vres.status == VerificationStatus.FAILED
    assert not vres.is_real_success
    assert "False success" in (vres.diagnostics or "") or "not created" in (vres.diagnostics or "") or "does not exist" in (vres.diagnostics or "")


def test_genuine_file_creation_verified(tmp_path):
    """Verify that a genuinely created file passes evidence-based verification."""
    real_file = str(tmp_path / "genuine_output.txt")
    with open(real_file, "w", encoding="utf-8") as f:
        f.write("Expected content inside file")

    step = PlanStep(
        step_id="step_file_2",
        description="Write output file",
        tool_name="write_file",
        parameters={"path": real_file},
        evidence_source="filesystem",
        postconditions=[f"file_exists:{real_file}", f"file_contains:{real_file}:Expected content"],
    )

    tool_output = "File saved successfully."
    vres = StepVerifier.verify_step_result(step, tool_output)

    assert vres.passed
    assert vres.status == VerificationStatus.PASSED
    assert vres.is_real_success


def test_false_success_screen_action_rejected():
    """Verify that screen action claiming success without UI evidence is rejected."""
    step = PlanStep(
        step_id="step_click_1",
        description="Click submit button",
        tool_name="click_element",
        parameters={"target_element": "ConfirmationDialog"},
        evidence_source="screen",
    )

    tool_output = "Clicked on coordinate (100, 200)"
    env_state = {"screen_state": {"elements": ["HomeScreen", "CancelButton"]}}  # ConfirmationDialog missing!

    vres = StepVerifier.verify_step_result(step, tool_output, environment_state=env_state)

    assert not vres.passed
    assert vres.status == VerificationStatus.FAILED
    assert not vres.is_real_success
    assert "ConfirmationDialog" in (vres.diagnostics or "")


def test_structured_output_verification():
    """Verify that structured output steps reject non-JSON / unstructured results."""
    step = PlanStep(
        step_id="step_calc",
        description="Calculate metrics",
        evidence_source="structured_output",
        postconditions=["json_key:total_score", "json_field:status:SUCCESS"],
    )

    # 1. Unstructured text claiming success -> rejected
    bad_output = "I calculated the score and it was 100!"
    vres_bad = StepVerifier.verify_step_result(step, bad_output)
    assert not vres_bad.passed

    # 2. Structured JSON missing field -> rejected
    partial_json = json.dumps({"total_score": 100, "status": "PENDING"})
    vres_partial = StepVerifier.verify_step_result(step, partial_json)
    assert not vres_partial.passed

    # 3. Valid JSON with correct fields -> passed
    valid_json = json.dumps({"total_score": 100, "status": "SUCCESS"})
    vres_valid = StepVerifier.verify_step_result(step, valid_json)
    assert vres_valid.passed


# ============================================================================
# 2. Bounded Recovery & Explanation Tests
# ============================================================================

def test_bounded_recovery_provides_explanation_and_respects_limits():
    """Verify that recovery explains why it is retrying and halts when limits are reached."""
    recovery_mgr = AutonomousRecoveryManager(max_retries_per_step=2, max_global_task_retries=3)

    step = PlanStep(
        step_id="step_flaky",
        description="Query network resource",
        tool_name="fetch_data",
        safety_level=SafetyLevel.SAFE,
    )

    # First failure
    diag1 = FailureAnalyzer.diagnose(step, error_msg="connection timed out")
    rec_step1 = recovery_mgr.record_and_generate_recovery_step(step, diag1)
    assert rec_step1 is not None
    assert "Retry #1" in rec_step1.description
    assert "timed out" in rec_step1.description.lower() or "connection" in rec_step1.description.lower()

    # Second failure
    diag2 = FailureAnalyzer.diagnose(step, error_msg="connection reset")
    rec_step2 = recovery_mgr.record_and_generate_recovery_step(step, diag2)
    assert rec_step2 is not None
    assert "Retry #2" in rec_step2.description

    # Third failure (exceeds max_retries_per_step=2)
    diag3 = FailureAnalyzer.diagnose(step, error_msg="socket error")
    rec_step3 = recovery_mgr.record_and_generate_recovery_step(step, diag3)
    assert rec_step3 is None  # Halted bounded retry!


def test_recovery_preserves_safety_level_and_authorization():
    """Verify that recovered steps retain SENSITIVE safety level and confirmation requirement."""
    recovery_mgr = AutonomousRecoveryManager(max_retries_per_step=2)

    sensitive_step = PlanStep(
        step_id="step_del",
        description="Delete temporary records",
        tool_name="delete_records",
        safety_level=SafetyLevel.SENSITIVE,
        requires_confirmation=True,
    )

    diag = FailureAnalyzer.diagnose(sensitive_step, error_msg="database locked")
    rec_step = recovery_mgr.record_and_generate_recovery_step(sensitive_step, diag)

    assert rec_step is not None
    assert rec_step.safety_level == SafetyLevel.SENSITIVE
    assert rec_step.requires_confirmation is True


# ============================================================================
# 3. End-to-End Execution with False-Success Detection Tests
# ============================================================================

def test_engine_detects_false_success_and_fails_plan(tmp_path):
    """Verify that TaskExecutionEngine rejects false-success tool outputs during full plan execution."""
    registry = ToolRegistry()
    fake_tool = FalseSuccessFileTool()
    registry.register(fake_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer, max_self_corrections_per_step=1)

    target_file = str(tmp_path / "never_created.txt")
    plan = TaskPlan(
        goal="Create important file",
        steps=[
            PlanStep(
                step_id="write_step",
                description="Write important file",
                tool_name="create_file",
                parameters={"path": target_file},
                evidence_source="filesystem",
                postconditions=[f"file_exists:{target_file}"],
            )
        ]
    )

    res = engine.execute_plan(plan)
    assert not res.success
    assert res.step_results["write_step"].status == StepStatus.FAILED
    assert "False success" in (res.step_results["write_step"].error or "") or "not created" in (res.step_results["write_step"].error or "")
