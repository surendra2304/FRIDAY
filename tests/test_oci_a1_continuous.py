import json
from pathlib import Path
from types import SimpleNamespace

from scripts.oci_a1_continuous import (
    AUTH_OR_CONFIG_ERROR_SECONDS,
    NO_CAPACITY_SECONDS,
    RATE_LIMIT_SECONDS,
    TRANSIENT_ERROR_SECONDS,
    AttemptResult,
    error_delay,
    persist_state,
    run_forever,
    safe_error,
)


class FakeStopEvent:
    def __init__(self):
        self.delays = []
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.delays.append(seconds)
        return self.stopped


class FakeAllocator:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def attempt_once(self):
        self.calls += 1
        return next(self.outcomes)


def test_retry_loop_continues_until_running_and_never_sleeps_after_success():
    allocator = FakeAllocator(
        [
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("retrying_after_error", TRANSIENT_ERROR_SECONDS),
            AttemptResult("allocated_running", 0, True),
        ]
    )
    stop_event = FakeStopEvent()

    assert run_forever(allocator, stop_event=stop_event) == 0
    assert allocator.calls == 3
    assert stop_event.delays == [NO_CAPACITY_SECONDS, TRANSIENT_ERROR_SECONDS]


def test_retry_loop_continues_across_repeated_no_capacity_results():
    allocator = FakeAllocator(
        [
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("allocated_running", 0, True),
        ]
    )
    stop_event = FakeStopEvent()

    run_forever(allocator, stop_event=stop_event)

    assert allocator.calls == 3
    assert stop_event.delays == [NO_CAPACITY_SECONDS, NO_CAPACITY_SECONDS]


def test_error_backoff_distinguishes_rate_limit_authorization_and_transient():
    assert error_delay(429, "TooManyRequests") == RATE_LIMIT_SECONDS
    assert error_delay(403, "NotAuthorizedOrNotFound") == AUTH_OR_CONFIG_ERROR_SECONDS
    assert error_delay(503, "ServiceError") == TRANSIENT_ERROR_SECONDS


def test_safe_error_returns_only_bounded_status_and_sanitized_code():
    exc = RuntimeError("secret response body must never be returned")
    exc.status = 403
    exc.code = "NotAuthorized / <unsafe>"
    status, code = safe_error(exc)

    assert status == 403
    assert code == "NotAuthorized____unsafe_"
    assert "secret response body" not in code


def test_state_persistence_is_atomic_and_contains_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("OCI_REGION", "ap-hyderabad-1")

    persist_state(
        "no_capacity",
        {"diagnostic": "capacity unavailable", "secret_value_must_not_be_passed": "not a secret"},
    )

    state = json.loads((Path(tmp_path) / "state.json").read_text(encoding="utf-8"))
    assert state["outcome"] == "no_capacity"
    assert state["target"]["region"] == "ap-hyderabad-1"
    assert state["details"]["diagnostic"] == "capacity unavailable"
    assert not (Path(tmp_path) / "state.json.tmp").exists()
