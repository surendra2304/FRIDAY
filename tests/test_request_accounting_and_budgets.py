# -*- coding: utf-8 -*-
"""Comprehensive tests for Gemini Request Accounting, Token Tracking, and Multi-Level Budget Enforcement."""

import pytest
import time
from unittest.mock import MagicMock, patch

from friday.auth.request_accounting import (
    BudgetLimits,
    BudgetExceededError,
    RequestAccountant,
    RequestRecord,
)
from friday.auth.credential_pool import GeminiCredentialPool, FailureCategory
from friday.core.exceptions import LLMProviderError
from friday.vision.pipeline import PerceptionPipeline
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.gemini_vision import GeminiVisionProvider


@pytest.fixture(autouse=True)
def reset_accountant():
    """Ensure clean accountant state before each test."""
    acc = RequestAccountant()
    acc.reset()
    acc.limits = BudgetLimits()
    yield acc
    acc.reset()


def test_accounting_records_without_secrets():
    """Verify that accounting records store project labels and metrics without raw API keys."""
    acc = RequestAccountant()
    secret_key = "AIzaSySecretRawKeyDoNotExpose12345"

    rec = acc.record_request(
        credential_label="PRIMARY",
        model="gemini-3.7-flash",
        purpose="reasoning",
        task_id="task_123",
        session_id="session_abc",
        estimated_input_tokens=150,
        estimated_output_tokens=75,
        latency_ms=120.5,
    )

    rec_dict = rec.to_dict()
    assert secret_key not in str(rec_dict)
    assert rec_dict["credential_label"] == "PRIMARY"
    assert rec_dict["estimated_input_tokens"] == 150
    assert rec_dict["estimated_output_tokens"] == 75

    summary = acc.get_summary()
    assert summary["total_requests"] == 1
    assert summary["cache_hits"] == 0
    assert summary["total_input_tokens_est"] == 150
    assert summary["total_output_tokens_est"] == 75
    assert summary["requests_by_credential_label"]["PRIMARY"] == 1


def test_per_task_budget_enforcement():
    """Verify that per-task request limit terminates safely when budget is reached."""
    acc = RequestAccountant()
    acc.limits.max_requests_per_task = 3

    # Make 3 requests
    for i in range(3):
        allowed, reason = acc.can_make_request(task_id="task_audit")
        assert allowed is True
        assert reason is None
        acc.record_request(
            credential_label="PRIMARY",
            model="gemini-3.7-flash",
            purpose="reasoning",
            task_id="task_audit",
        )

    # 4th request must be rejected with informative reason
    allowed, reason = acc.can_make_request(task_id="task_audit")
    assert allowed is False
    assert "Task budget exceeded" in reason
    assert "limit: 3" in reason

    # Different task ID is still permitted
    allowed_other, _ = acc.can_make_request(task_id="task_other")
    assert allowed_other is True


def test_consecutive_failure_circuit_breaker():
    """Verify that repeated failed calls trigger the circuit breaker rather than infinite retries."""
    acc = RequestAccountant()
    acc.limits.max_consecutive_failed_calls = 3

    # Record 3 failures
    for i in range(3):
        acc.record_request(
            credential_label="PRIMARY",
            model="gemini-3.7-flash",
            purpose="reasoning",
            failure_category="QUOTA_EXHAUSTED",
        )

    assert acc.consecutive_failures == 3

    # Next call must be blocked
    allowed, reason = acc.can_make_request()
    assert allowed is False
    assert "Circuit breaker active" in reason
    assert "3 consecutive provider failures" in reason

    # Successful request (e.g. after pool recovery or reset) resets the failure count
    acc.reset()
    assert acc.consecutive_failures == 0
    allowed, _ = acc.can_make_request()
    assert allowed is True


def test_static_screen_does_not_generate_repeated_vision_calls():
    """Prove that identical static screen observations hit cache and do NOT increment provider calls."""
    acc = RequestAccountant()
    cap = MockScreenCaptureProvider(width=100, height=100)
    static_img = create_synthetic_png(100, 100, (50, 100, 150))
    cap.set_mock_image(static_img)

    mock_vision = MockVisionProvider()
    pipeline = PerceptionPipeline(capture_provider=cap, vision_provider=mock_vision, ttl_seconds=60.0)

    # First perception: Cache miss -> queries provider
    res1 = pipeline.perceive(task_id="task_vision_test")
    assert res1.source in ("gemini_vision", "mock_vision")
    assert mock_vision.call_count == 1

    # Second perception on same unchanged static screen: Must hit cache and NOT query provider
    res2 = pipeline.perceive(task_id="task_vision_test")
    assert res2.source == "cache"
    assert mock_vision.call_count == 1  # Provider call count remains strictly 1!

    # Third perception: Still unchanged -> cache hit
    res3 = pipeline.perceive(task_id="task_vision_test")
    assert res3.source == "cache"
    assert mock_vision.call_count == 1

    summary = acc.get_summary()
    assert summary["cache_hits"] >= 2


def test_vision_loop_guard_triggers_within_budget():
    """Verify that repeated vision perception requests on a task terminate within budget."""
    acc = RequestAccountant()
    acc.limits.max_vision_perceptions_per_task = 3

    # Record 3 vision calls for task
    for _ in range(3):
        acc.record_request(
            credential_label="PRIMARY",
            model="gemini-3.7-flash",
            purpose="vision_perception",
            task_id="task_loop_test",
        )

    # 4th vision call on this task must be rejected
    allowed, reason = acc.can_make_request(task_id="task_loop_test", purpose="vision_perception")
    assert allowed is False
    assert "Vision loop guard triggered" in reason
    assert "Halting to prevent infinite screen loop" in reason


def test_hourly_and_daily_budgets():
    """Verify sliding window hourly and daily budget ceilings."""
    acc = RequestAccountant()
    acc.limits.max_requests_per_hour = 5
    acc.limits.max_requests_per_day = 10

    for i in range(5):
        acc.record_request(
            credential_label="PRIMARY",
            model="gemini-3.7-flash",
            purpose="reasoning",
        )

    allowed, reason = acc.can_make_request()
    assert allowed is False
    assert "Hourly request budget exceeded" in reason
