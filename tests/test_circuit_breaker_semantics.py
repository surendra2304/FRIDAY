
import pytest

from friday.auth.request_accounting import (
    BudgetLimits,
    CircuitBreakerState,
)


@pytest.fixture
def accountant():
    # Use reset() to clean state without breaking the module-level singleton reference.
    # Setting _instance=None creates a new object that diverges from the imported
    # `request_accountant` variable, causing cross-test contamination.
    from friday.auth.request_accounting import request_accountant
    original_limits = request_accountant.limits
    request_accountant.reset()
    request_accountant.limits = BudgetLimits(
        max_consecutive_failed_calls=3,
        circuit_breaker_cooldown_seconds=0.1
    )
    yield request_accountant
    request_accountant.reset()
    request_accountant.limits = original_limits

def test_circuit_breaker_transitions(accountant):
    # Initial state
    assert accountant.circuit_state == CircuitBreakerState.CLOSED
    
    # 3 failures -> OPEN
    for _ in range(3):
        accountant.record_request(
            credential_label="PRIMARY",
            model="test-model",
            purpose="reasoning",
            failure_category="network_error"
        )
    
    assert accountant.circuit_state == CircuitBreakerState.OPEN
    
    # Should block immediately with CIRCUIT_BLOCK (circuit breaker active)
    allowed, reason = accountant.can_make_request()
    assert not allowed
    assert "Circuit breaker active" in reason
    
    # Cooldown expires -> HALF_OPEN
    import time
    time.sleep(0.15)
    
    allowed, reason = accountant.can_make_request()
    # can_make_request transitions to HALF_OPEN but the check itself might return true or wait
    assert accountant.circuit_state == CircuitBreakerState.HALF_OPEN
    
    # Probe request succeeds
    accountant.record_request(
        credential_label="PRIMARY",
        model="test-model",
        purpose="reasoning",
        failure_category=None  # Success
    )
    
    assert accountant.circuit_state == CircuitBreakerState.CLOSED
    assert accountant.consecutive_failures == 0

def test_circuit_breaker_probe_fails(accountant):
    # 3 failures -> OPEN
    for _ in range(3):
        accountant.record_request(
            credential_label="PRIMARY",
            model="test-model",
            purpose="reasoning",
            failure_category="network_error"
        )
    
    import time
    time.sleep(0.15)
    accountant.can_make_request()  # triggers HALF_OPEN
    assert accountant.circuit_state == CircuitBreakerState.HALF_OPEN
    
    # Probe request fails
    accountant.record_request(
        credential_label="PRIMARY",
        model="test-model",
        purpose="reasoning",
        failure_category="network_error"
    )
    
    # Back to OPEN
    assert accountant.circuit_state == CircuitBreakerState.OPEN

def test_budget_blocks_do_not_count_as_provider_failures(accountant):
    assert accountant.circuit_state == CircuitBreakerState.CLOSED
    
    # These should NOT increment consecutive failures
    for _ in range(5):
        accountant.record_request(
            credential_label="PRIMARY",
            model="test-model",
            purpose="reasoning",
            failure_category="budget_block"
        )
    
    assert accountant.circuit_state == CircuitBreakerState.CLOSED
    assert accountant.consecutive_failures == 0
