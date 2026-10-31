"""Tests for multi-agent consensus routing pipelines and dynamic retry jitter."""

import pytest
import respx
import httpx

from friday.agent.execution_trace import ExecutionTraceStore
from friday.agent.router import (
    SpecialistRouter,
    compute_backoff_jitter,
    parse_retry_after,
)
from friday.core.task_envelope import TaskEnvelope, TaskStatus


def test_compute_backoff_jitter_bounds_and_strategies():
    # 1. Full jitter: between 0 and min(cap, base * 2^(attempt-1))
    for attempt in range(1, 6):
        delay = compute_backoff_jitter(attempt, base_seconds=0.2, cap_seconds=3.0, strategy="full")
        max_possible = min(3.0, 0.2 * (2 ** (attempt - 1)))
        assert 0.0 <= delay <= max_possible + 1e-6

    # 2. Equal jitter: half deterministic, half jitter
    for attempt in range(1, 5):
        delay = compute_backoff_jitter(attempt, base_seconds=0.2, cap_seconds=2.0, strategy="equal")
        exp_delay = min(2.0, 0.2 * (2 ** (attempt - 1)))
        half = exp_delay / 2.0
        assert half <= delay <= exp_delay + 1e-6

    # 3. Decorrelated jitter
    prev = 0.5
    for _ in range(5):
        delay = compute_backoff_jitter(1, base_seconds=0.1, cap_seconds=2.0, strategy="decorrelated", prev_delay=prev)
        assert 0.1 <= delay <= 2.0
        prev = delay


def test_parse_retry_after():
    req = httpx.Request("POST", "http://test:8000")
    resp_with_header = httpx.Response(429, request=req, headers={"retry-after": "2.5"})
    assert parse_retry_after(resp_with_header) == 2.5

    resp_invalid = httpx.Response(429, request=req, headers={"retry-after": "invalid"})
    assert parse_retry_after(resp_invalid, default=1.5) == 1.5

    resp_none = httpx.Response(200, request=req)
    assert parse_retry_after(resp_none, default=0.5) == 0.5


@pytest.fixture
def isolated_router(tmp_path):
    db_path = str(tmp_path / "test_router_traces.db")
    store = ExecutionTraceStore(db_path=db_path)
    router = SpecialistRouter(
        timeout_ceiling=5.0,
        max_retries=2,
        trace_storage=store,
        jitter_strategy="full",
    )
    yield router, store


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_consensus_majority_achieved(isolated_router):
    router, store = isolated_router

    # Mock 3 panel agents: 2 say BUY, 1 says HOLD
    respx.post("http://inference:8000/v1/tasks").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "BUY", "confidence": 0.95}, "summary": "Bullish signals"})
    )
    respx.post("http://cortex:8000/v1/tasks").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "BUY", "confidence": 0.88}, "summary": "Market traction confirms"})
    )
    respx.post("http://futuris:8000/v1/tasks").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "HOLD", "confidence": 0.60}, "summary": "Moderate volatility expected"})
    )

    envelope = TaskEnvelope(
        action="evaluate_position",
        objective="Determine next portfolio position",
        inputs={"ticker": "BTC/USDT"},
    )

    consensus = await router.dispatch_consensus(
        envelope,
        agents=["inference", "cortex", "futuris"],
        quorum_threshold=0.5,
        min_quorum=2,
    )

    assert consensus.consensus_reached is True
    assert consensus.consensus_status == "ACHIEVED"
    assert consensus.winning_decision == "buy"
    assert consensus.quorum_count == 3
    assert round(consensus.agreement_ratio, 2) == 0.67
    assert len(consensus.votes) == 3

    # Check persistence
    traces = store.get_consensus_traces(limit=5)
    assert len(traces) == 1
    assert traces[0].consensus_status == "ACHIEVED"
    assert traces[0].target_agent == "consensus"


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_consensus_unanimous_failure_when_divergent(isolated_router):
    router, store = isolated_router

    respx.post("http://inference:8000/v1/tasks").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "APPROVE"}})
    )
    respx.post("http://sentinel:8000/api/v1/friday/delegate").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "DENY"}})
    )

    envelope = TaskEnvelope(
        action="security_check",
        objective="Verify system deployment policy",
    )

    consensus = await router.dispatch_consensus(
        envelope,
        agents=["inference", "sentinel"],
        strategy="unanimous",
        min_quorum=2,
    )

    assert consensus.consensus_reached is False
    assert consensus.consensus_status == "DIVERGENT"
    assert consensus.agreement_ratio == 0.5


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_consensus_handles_partial_quorum(isolated_router):
    router, store = isolated_router

    # inference succeeds, cortex times out, futuris returns 500
    respx.post("http://inference:8000/v1/tasks").mock(
        return_value=httpx.Response(200, json={"result": {"decision": "PROCEED"}})
    )
    respx.post("http://cortex:8000/v1/tasks").mock(
        side_effect=httpx.ConnectTimeout("Cortex timeout")
    )
    respx.post("http://futuris:8000/v1/tasks").mock(
        return_value=httpx.Response(500, json={"error": "Internal server error"})
    )

    envelope = TaskEnvelope(action="deep_analysis")

    # Requires min_quorum=2, but only 1 succeeded
    consensus = await router.dispatch_consensus(
        envelope,
        agents=["inference", "cortex", "futuris"],
        min_quorum=2,
    )

    assert consensus.consensus_reached is False
    assert consensus.consensus_status == "PARTIAL_QUORUM"
    assert consensus.quorum_count == 1


@pytest.mark.asyncio
async def test_dispatch_consensus_blocked_by_safety_gate(isolated_router):
    router, store = isolated_router

    envelope = TaskEnvelope(
        action="trade_override",
        inputs={"bypass_risk_limits": True},
    )

    # stratex is in the panel, which forbids bypass_risk_limits
    consensus = await router.dispatch_consensus(
        envelope,
        agents=["inference", "stratex"],
    )

    assert consensus.consensus_reached is False
    assert consensus.consensus_status == "FAILED"
    assert "Consensus blocked" in consensus.synthesized_output.get("error", "")

    traces = store.get_recent_traces(limit=5)
    assert len(traces) == 1
    assert traces[0].status == TaskStatus.BLOCKED.value
