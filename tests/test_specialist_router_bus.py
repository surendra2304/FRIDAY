"""Unit tests for FRIDAY Specialist Dispatch Bus and Architectural Invariants."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from friday.agent.router import (
    SPECIALIST_CONFIGS,
    SafetyGateViolationError,
    SpecialistRouter,
    _is_truthy,
    specialist_router,
)
from friday.core.task_envelope import TaskEnvelope, TaskPriority, TaskResult, TaskStatus


def test_is_truthy_helper():
    """Verify _is_truthy helper accurately parses diverse truthy and falsey inputs."""
    assert _is_truthy(True) is True
    assert _is_truthy(1) is True
    assert _is_truthy("true") is True
    assert _is_truthy("TRUE") is True
    assert _is_truthy("yes") is True
    assert _is_truthy("1") is True

    assert _is_truthy(False) is False
    assert _is_truthy(0) is False
    assert _is_truthy("false") is False
    assert _is_truthy("no") is False
    assert _is_truthy(None) is False
    assert _is_truthy([]) is False


def test_specialist_endpoints_port_compliance():
    """Verify all 9 specialist peer agents are configured on container port 8000 and Render URLs eradicated."""
    router = SpecialistRouter()
    for agent_id, cfg in SPECIALIST_CONFIGS.items():
        url = router.get_agent_url(agent_id)
        assert ":8000" in url, f"Agent {agent_id} must target port 8000 (got {url})"
        assert "onrender.com" not in url, f"Agent {agent_id} cannot reference dead onrender.com"
        assert ":5000" not in url, f"Agent {agent_id} cannot reference legacy port 5000"


def test_resolve_target_agent_by_directive():
    """Verify domain keywords route to the correct specialist agents."""
    router = SpecialistRouter()
    assert router.resolve_target_agent("Place a market order for BTC futures") == "stratex"
    assert router.resolve_target_agent("Scan dockerfile for security vulnerabilities") == "sentinel"
    assert router.resolve_target_agent("Build and compile test patch in sandbox") == "forge"
    assert router.resolve_target_agent("Research macro trend news on web") == "intelx"
    assert router.resolve_target_agent("Scrape web page and extract table") == "cortex"
    assert router.resolve_target_agent("Calculate probabilistic forecast timeline") == "futuris"
    assert router.resolve_target_agent("Produce and render youtube video") == "vyralx"
    assert router.resolve_target_agent("Recall episodic profile memory") == "memora"
    assert router.resolve_target_agent("Reason about quantum computing logic") == "inference"


@pytest.mark.asyncio
async def test_safety_invariant_1_stratex_risk_override_blocked():
    """Verify FRIDAY Core CANNOT override Stratex risk limits, even with string truthy values."""
    router = SpecialistRouter()
    envelope = TaskEnvelope(
        target_agent="stratex",
        action="execute_trade",
        inputs={"symbol": "BTCUSDT", "bypass_risk_limits": "true"},
    )

    result = await router.dispatch_envelope(envelope)
    assert result.status == TaskStatus.BLOCKED
    assert "Safety Invariant 1 Violation" in result.error
    assert "Stratex risk limits" in result.error
    assert result.receipt.authorization_decision == "REJECTED"


@pytest.mark.asyncio
async def test_safety_invariant_1_sentinel_veto_override_blocked():
    """Verify FRIDAY Core CANNOT bypass Sentinel security vetoes across any mesh target."""
    router = SpecialistRouter()
    # Attempting to bypass security when targeting another peer agent (e.g. cortex)
    envelope = TaskEnvelope(
        target_agent="cortex",
        action="scrape_internal_admin",
        inputs={"url": "http://admin", "skip_sentinel": "yes"},
    )

    result = await router.dispatch_envelope(envelope)
    assert result.status == TaskStatus.BLOCKED
    assert "Sentinel security vetoes" in result.error


@pytest.mark.asyncio
async def test_safety_invariant_1_forge_sandbox_breakout_blocked():
    """Verify FRIDAY Core CANNOT breach Forge sandbox boundaries, even with int 1 flag."""
    router = SpecialistRouter()
    envelope = TaskEnvelope(
        target_agent="forge",
        action="run_build",
        inputs={"command": "make test", "escape_sandbox": 1},
    )

    result = await router.dispatch_envelope(envelope)
    assert result.status == TaskStatus.BLOCKED
    assert "Forge sandbox boundaries" in result.error


@pytest.mark.asyncio
async def test_safety_invariant_3_desktop_win32_boundary_enforced():
    """Verify Win32 native APIs cannot be routed to Linux container peer agents."""
    router = SpecialistRouter()
    envelope = TaskEnvelope(
        target_agent="cortex",
        action="automate_window",
        inputs={"pywinauto_action": True, "window_title": "Notepad"},
    )

    result = await router.dispatch_envelope(envelope)
    assert result.status == TaskStatus.BLOCKED
    assert "Safety Invariant 3 Violation" in result.error
    assert "Linux container peer" in result.error


@pytest.mark.asyncio
async def test_safety_invariant_2_commit_durable_memory_to_memora():
    """Verify durable memories are committed to Memora REST API."""
    router = SpecialistRouter()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "stored",
        "memory_id": "mem_123",
        "result": {"acknowledged": True},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        res = await router.commit_durable_memory_to_memora({"key": "user_preference", "val": "concise"})
        assert res.status == TaskStatus.SUCCESS
        assert res.target_agent == "memora"
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "memora:8000/v1/tasks" in call_url or "memora" in call_url


@pytest.mark.asyncio
async def test_circuit_breaker_and_graceful_degradation():
    """Verify router trips circuit breaker after consecutive failures without crashing master loop."""
    router = SpecialistRouter(
        max_retries=1,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=30.0,
    )

    envelope = TaskEnvelope(
        target_agent="futuris",
        action="forecast",
        inputs={"query": "GDP growth 2027"},
    )

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        # 1. First failure
        res1 = await router.dispatch_envelope(envelope)
        assert res1.status == TaskStatus.DEGRADED
        assert "ConnectError" in res1.error

        # 2. Second failure (exceeds failure_threshold=2 -> trips circuit breaker to OPEN)
        res2 = await router.dispatch_envelope(envelope)
        assert res2.status == TaskStatus.DEGRADED

        # 3. Third call while circuit breaker is OPEN -> short-circuits immediately
        res3 = await router.dispatch_envelope(envelope)
        assert res3.status == TaskStatus.DEGRADED
        assert "circuit OPEN" in res3.summary
        assert "Circuit breaker for specialist 'futuris' is OPEN" in res3.error


@pytest.mark.asyncio
async def test_successful_envelope_dispatch_roundtrip():
    """Verify normal successful TaskEnvelope roundtrip across mesh."""
    router = SpecialistRouter()
    envelope = TaskEnvelope(
        target_agent="intelx",
        action="osint_query",
        objective="Fetch recent news on AI safety standards",
        inputs={"sources": ["arxiv", "reuters"]},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "summary": "IntelX found 12 validated research papers",
        "result": {"count": 12, "top_url": "https://arxiv.org/abs/2601.0001"},
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await router.dispatch_envelope(envelope)

        assert res.status == TaskStatus.SUCCESS
        assert res.target_agent == "intelx"
        assert res.summary == "IntelX found 12 validated research papers"
        assert res.result["count"] == 12
        assert res.receipt.authorization_decision == "AUTHORIZED"
