# -*- coding: utf-8 -*-
"""Adversarial and recursive sanitization tests for memory persistence models."""

import json
import pytest
from friday.security.scrubber import recursive_sanitize
from friday.memory.task_context import ActiveTaskContext, TaskObservation
from friday.agent.checkpoint import TaskCheckpoint, InterruptionReason, TaskState
from friday.agent.goal import Goal, GoalRequestType, GoalRiskLevel, SubGoal
from friday.agent.planner import TaskPlan, PlanStep, StepStatus, SafetyLevel


def test_recursive_nested_data_sanitization():
    """Verify that recursive_sanitize scrubs secrets deeply nested in dicts, lists, and tuples."""
    adversarial_payload = {
        "user_profile": {
            "name": "Alice",
            "db_password": "supersecretpassword123",
            "api_keys_list": [
                "sk-proj-99887766554433221100abcde",
                {"service": "gemini", "secret_key_field": "AIzaSyCDE1234567890abcd_efgh_ijkl_mnop"}
            ]
        },
        "session_details": (
            "Cookie: session_id=abc123xyz789",
            "Authorization: Bearer my_oauth_token_val_1"
        )
    }

    sanitized = recursive_sanitize(adversarial_payload)

    # Asserts
    assert sanitized["user_profile"]["db_password"] == "[REDACTED_SECRET]"
    # Since api_keys_list contains "key", the key itself matches the sensitive term filter and is redacted completely
    assert sanitized["user_profile"]["api_keys_list"] == "[REDACTED_SECRET]"
    assert sanitized["session_details"][0] == "Cookie: [REDACTED_SECRET]"
    assert sanitized["session_details"][1] in ("Authorization: [REDACTED_SECRET]", "Authorization: Bearer [REDACTED_TOKEN]")


def test_json_string_deep_redaction():
    """Verify that JSON strings containing nested secrets are decoded, scrubbed, and re-encoded."""
    inner_json = json.dumps({
        "admin_secret": "my-admin-password-value",
        "api_key": "sk-proj-abcdef1234567890"
    })
    outer_payload = {
        "id": "123",
        "config_json_str": inner_json
    }

    sanitized = recursive_sanitize(outer_payload)
    assert "sk-proj-" not in sanitized["config_json_str"]
    assert "my-admin-password" not in sanitized["config_json_str"]

    # Decode and verify structure remains intact
    decoded_inner = json.loads(sanitized["config_json_str"])
    assert decoded_inner["admin_secret"] == "[REDACTED_SECRET]"
    assert decoded_inner["api_key"] == "[REDACTED_SECRET]"


def test_base64_image_and_binary_redaction():
    """Verify base64 screenshots and raw binary blobs are redacted safely."""
    image_payload = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADIA..."
    raw_binary = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00"

    sanitized_img = recursive_sanitize(image_payload)
    sanitized_bin = recursive_sanitize(raw_binary)

    assert sanitized_img == "[REDACTED_IMAGE]"
    assert sanitized_bin == b"[REDACTED_BINARY]"


def test_active_task_context_serialization_leakage_protection():
    """Verify ActiveTaskContext to_dict/from_dict prevents sensitive credentials from leaking."""
    # Use valid length test credentials: 33 characters after AIzaSy, 20+ characters after sk-proj-
    ctx = ActiveTaskContext(goal="Extract private key AIzaSyA1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p")
    ctx.step_outputs["step_1"] = "Database connection postgresql://admin:secret_pass@localhost/db established"
    ctx.observations.append(TaskObservation(step_id="step_1", content="Found API token sk-proj-1234567890abcdef12345"))

    # Serialize
    serialized = ctx.to_dict()

    # Verify no raw secrets persist in serialization
    serialized_str = json.dumps(serialized)
    assert "AIzaSy" not in serialized_str
    assert "secret_pass" not in serialized_str
    assert "sk-proj-" not in serialized_str

    # Restore and verify restored state is clean
    restored = ActiveTaskContext.from_dict(serialized)
    assert "AIzaSy" not in restored.goal
    assert "secret_pass" not in restored.step_outputs["step_1"]
    assert "sk-proj-" not in restored.observations[0].content


def test_task_checkpoint_serialization_leakage_protection():
    """Verify TaskCheckpoint to_dict/from_dict redacts nested credentials."""
    chk = TaskCheckpoint(
        checkpoint_id="chk_001",
        task_id="task_001",
        goal="Configure cloud using password=my_secure_pass",
        state=TaskState.PAUSED,
        active_step_id="step_2",
        plan_dict={"steps": [{"step_id": "s1", "parameters": {"secret_key_field": "sk-proj-xyz"}}]},
        completed_steps=["s1"],
        pending_steps=["step_2"],
        step_results={"s1": "Authorization: Basic dXNlcjpwYXNz"},
        environment_hash="env_hash_1"
    )

    serialized = chk.to_dict()
    serialized_str = json.dumps(serialized)
    assert "my_secure_pass" not in serialized_str
    assert "sk-proj-" not in serialized_str
    assert "dXNlcjpwYXNz" not in serialized_str

    restored = TaskCheckpoint.from_dict(serialized)
    assert "my_secure_pass" not in restored.goal
    assert "sk-proj-" not in restored.plan_dict["steps"][0]["parameters"]["secret_key_field"]
    assert "dXNlcjpwYXNz" not in restored.step_results["s1"]
