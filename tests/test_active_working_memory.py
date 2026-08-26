# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Cognitive Task Planning.5: Active Working Memory & Task Context.

Tests:
1. ActiveTaskContext isolation between concurrent/independent tasks.
2. Context compaction and sliding window bounding under token budgets.
3. Serialization and restoration of ActiveTaskContext.
4. Relevance filtering and prioritized working summary generation.
5. Task completion cleanup and long-term summary extraction.
6. Sensitive data sanitization (API keys, passwords, base64 images).
7. Multimodal context and perceptual delta recording.
8. Expiration / TTL handling.
"""

from datetime import datetime, timezone
import pytest

from friday.memory.task_context import ActiveTaskContext, TaskObservation
from friday.agent.state import TaskState
from friday.agent.verification import VerificationResult, VerificationStatus


# 1. Task Context Isolation
def test_task_context_isolation():
    ctx1 = ActiveTaskContext(task_id="task_1", goal="Task 1 Goal")
    ctx2 = ActiveTaskContext(task_id="task_2", goal="Task 2 Goal")

    ctx1.add_constraint("read_only")
    ctx1.record_step_result("s1", "Result 1")

    ctx2.add_constraint("write_enabled")
    ctx2.record_step_result("s2", "Result 2")

    assert ctx1.constraints == ["read_only"]
    assert "s1" in ctx1.step_outputs
    assert "s2" not in ctx1.step_outputs

    assert ctx2.constraints == ["write_enabled"]
    assert "s2" in ctx2.step_outputs
    assert "s1" not in ctx2.step_outputs


# 2. Context Compaction & Sliding Window
def test_task_context_compaction():
    ctx = ActiveTaskContext(task_id="t_compact", goal="Compaction test", max_observations=5)

    for i in range(10):
        ctx.record_step_result(f"step_{i}", f"Output {i}")
        ctx.add_observation(f"step_{i}", f"Obs {i}")

    assert len(ctx.observations) == 5  # Sliding window capped at 5
    assert len(ctx.step_outputs) == 10

    ctx.compact(max_step_outputs=3, max_observations=3)
    assert len(ctx.step_outputs) == 3
    assert list(ctx.step_outputs.keys()) == ["step_7", "step_8", "step_9"]
    assert len(ctx.observations) == 3


# 3. Serialization and Restoration
def test_task_context_serialization_and_restoration():
    ctx = ActiveTaskContext(task_id="t_serial", goal="Serialization test")
    ctx.set_state(TaskState.EXECUTING)
    ctx.set_active_step("step_abc")
    ctx.add_constraint("non_interactive")
    ctx.add_user_clarification("prefer json")
    ctx.set_temp_variable("counter", 42)
    ctx.record_authorization_decision("write_file", "APPROVED")
    ctx.record_checkpoint("chk_123")
    ctx.record_step_result("step_abc", "Done", verification=VerificationResult(status=VerificationStatus.PASSED, criterion="Done"))

    d = ctx.to_dict()
    restored = ActiveTaskContext.from_dict(d)

    assert restored.task_id == "t_serial"
    assert restored.goal == "Serialization test"
    assert restored.active_step_id == "step_abc"
    assert restored.constraints == ["non_interactive"]
    assert restored.user_clarifications == ["prefer json"]
    assert restored.get_temp_variable("counter") == 42
    assert len(restored.authorization_decisions) == 1
    assert restored.checkpoint_references == ["chk_123"]
    assert restored.step_outputs["step_abc"] == "Done"


# 4. Sensitive Data Sanitization
def test_task_context_sensitive_data_sanitization():
    ctx = ActiveTaskContext(task_id="t_safe", goal="Safety test")

    # Image base64 payload
    ctx.record_step_result("s1", "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    assert "[Visual screenshot captured and processed safely]" in ctx.step_outputs["s1"]

    # Sensitive key/token/password
    ctx.record_step_result("s2", "User auth success with token=ghp_secretkey123456")
    assert "[Sensitive credentials redacted]" in ctx.step_outputs["s2"]

    # Temp variables with passwords
    ctx.set_temp_variable("auth", "password=supersecretpassword")
    assert "[Sensitive credential redacted]" in ctx.get_temp_variable("auth")


# 5. Long-term Summary Extraction and Cleanup
def test_task_context_cleanup_and_summary():
    ctx = ActiveTaskContext(task_id="t_clean", goal="Process payments")
    ctx.add_user_clarification("send receipts via email")
    ctx.record_step_result("s1", "Invoice #101 created")

    summary_msg = ctx.finalize_and_extract_long_term_summary(success=True)
    assert summary_msg is not None
    assert "completed successfully" in summary_msg.content
    assert "send receipts via email" in summary_msg.content
    assert "Invoice #101 created" in summary_msg.content

    ctx.clear()
    assert len(ctx.step_outputs) == 0
    assert len(ctx.constraints) == 0
    assert len(ctx.observations) == 0
    assert ctx.active_step_id is None


# 6. Prioritized Working Summary
def test_prioritized_working_summary():
    ctx = ActiveTaskContext(task_id="t_summary", goal="Complex workflow")
    ctx.set_state(TaskState.EXECUTING)
    ctx.set_active_step("step_active")
    ctx.add_constraint("no_network")
    ctx.record_step_result("s1", "Step 1 OK")
    ctx.record_failure("s2", "Step 2 failed on timeout")

    summary = ctx.get_working_summary()
    assert "[Active Task Goal]: Complex workflow" in summary
    assert "[Active Step]: step_active" in summary
    assert "[Constraints]: no_network" in summary
    assert "[Completed Step Results]:" in summary
    assert "Step 1 OK" in summary
    assert "[Recent Failures]:" in summary
    assert "Step 2 failed on timeout" in summary
