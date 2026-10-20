"""Regression tests for the scheduled engineering runner's retry window."""

from scripts.continuous_engineering_local_runner import (
    MAX_CONSECUTIVE_FAST_FAILURES,
    FAST_FAILURE_SECONDS,
    next_fast_failure_streak,
    should_stop_after_fast_failures,
)


def test_success_resets_fast_failure_streak() -> None:
    assert next_fast_failure_streak(0, 1.0, 2) == 0


def test_fast_failure_increments_streak() -> None:
    assert next_fast_failure_streak(1, FAST_FAILURE_SECONDS - 1, 1) == 2


def test_slow_timeout_does_not_count_as_persistent_fast_failure() -> None:
    assert next_fast_failure_streak(124, FAST_FAILURE_SECONDS, 2) == 0


def test_abort_requires_three_consecutive_fast_failures() -> None:
    assert not should_stop_after_fast_failures(MAX_CONSECUTIVE_FAST_FAILURES - 1)
    assert should_stop_after_fast_failures(MAX_CONSECUTIVE_FAST_FAILURES)
