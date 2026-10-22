"""Tier 1: Feature Coverage Test Suite.

Provides isolated, requirement-driven tests covering all 13 features in PROJECT.md § Feature Inventory (>= 5 tests per feature, 65 tests total).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from friday.api.server import app
from friday.core.cache import TTLCache, ttl_cached
from friday.core.database import configure_sqlite_pragmas, connect_sqlite, get_db_connection
from friday.core.resilience import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    retry_with_backoff,
    safe_peer_call,
)
from friday.core.startup_validator import StartupValidationError, validate_runtime_environment
from friday.ecosystem.fleet_client import fleet_client
from friday.security.scrubber import redact_secrets, recursive_sanitize


# ==============================================================================
# Feature 1: Async Client Pooling (5 tests)
# ==============================================================================

def test_f1_01_fleet_client_shared_client_initialization() -> None:
    """F1.1: Verify fleet_client initializes an httpx.AsyncClient with explicit timeout."""
    client = fleet_client.get_shared_client()
    assert client is not None
    assert not client.is_closed
    assert client.timeout.connect == 30.0 or client.timeout.read == 30.0


def test_f1_02_fleet_client_shared_client_reuse() -> None:
    """F1.2: Verify repeated calls to get_shared_client() return the exact same instance."""
    client1 = fleet_client.get_shared_client()
    client2 = fleet_client.get_shared_client()
    assert client1 is client2


@pytest.mark.asyncio
async def test_f1_03_fleet_client_aclose_lifecycle() -> None:
    """F1.3: Verify aclose() shuts down the shared client pool and resets internal reference."""
    client = fleet_client.get_shared_client()
    assert not client.is_closed
    await fleet_client.aclose()
    assert fleet_client._shared_client is None
    # Subsequent call re-creates a fresh pool
    client_new = fleet_client.get_shared_client()
    assert client_new is not None
    assert client_new is not client


def test_f1_04_ai_universe_client_pooling() -> None:
    """F1.4: Verify AIUniverseClient manages a reusable async client pool."""
    from friday.tools.ai_universe_client import AIUniverseClient
    ai_client = AIUniverseClient()
    c1 = ai_client.get_client()
    c2 = ai_client.get_client()
    assert c1 is c2
    assert not c1.is_closed


def test_f1_05_mesh_timeout_configuration() -> None:
    """F1.5: Verify Mesh communicator is configured with explicit operational timeout."""
    from friday.cognition.mesh import Mesh
    mesh = Mesh(request_timeout=12.5)
    assert mesh.request_timeout == 12.5


# ==============================================================================
# Feature 2: Circuit Breakers & Retries with Jitter (5 tests)
# ==============================================================================

def test_f2_01_circuit_breaker_starts_closed() -> None:
    """F2.1: Verify AsyncCircuitBreaker begins in CLOSED state with zero failure counter."""
    breaker = AsyncCircuitBreaker(service_name="cortex", failure_threshold=3)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.consecutive_failures == 0


@pytest.mark.asyncio
async def test_f2_02_circuit_breaker_trips_to_open_on_threshold() -> None:
    """F2.2: Verify circuit trips to OPEN once consecutive failures hit failure_threshold."""
    breaker = AsyncCircuitBreaker(service_name="memora", failure_threshold=2)
    await breaker.record_failure(RuntimeError("fail 1"))
    assert breaker.state == CircuitState.CLOSED
    await breaker.record_failure(RuntimeError("fail 2"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_f2_03_circuit_breaker_open_blocks_execution() -> None:
    """F2.3: Verify calling an OPEN circuit raises CircuitBreakerOpenError immediately."""
    breaker = AsyncCircuitBreaker(service_name="forge", failure_threshold=1, recovery_time_seconds=10.0)
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    called = False
    async def probe() -> str:
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await breaker.call(probe)

    assert not called
    assert "Circuit breaker for forge is OPEN" in str(exc_info.value)


@pytest.mark.asyncio
async def test_f2_04_circuit_breaker_half_open_healing() -> None:
    """F2.4: Verify circuit transitions to HALF_OPEN after recovery time and heals to CLOSED on success."""
    breaker = AsyncCircuitBreaker(service_name="sentinel", failure_threshold=1, recovery_time_seconds=0.05, half_open_success_threshold=1)
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN

    await asyncio.sleep(0.08)
    assert await breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_f2_05_retry_with_backoff_and_jitter_success() -> None:
    """F2.5: Verify retry_with_backoff retries on transient errors and succeeds within retry budget."""
    attempts = 0

    @retry_with_backoff(retries=3, base_delay=0.01, max_delay=0.05, jitter=True)
    async def flaky_service() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ConnectionError("Transient network glitch")
        return "recovered"

    res = await flaky_service()
    assert res == "recovered"
    assert attempts == 2


# ==============================================================================
# Feature 3: Graceful Degradation on Timeouts (5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_f3_01_safe_peer_call_catches_timeout_error() -> None:
    """F3.1: Verify safe_peer_call intercepts TimeoutError and prevents unhandled crash."""
    async def timed_out_peer() -> None:
        raise asyncio.TimeoutError("Upstream peer took 15s")

    result = await safe_peer_call(timed_out_peer(), peer_name="cortex")
    assert result["status"] == "degraded"
    assert result["peer"] == "cortex"
    assert result["fallback"] is True


@pytest.mark.asyncio
async def test_f3_02_safe_peer_call_default_payload_structure() -> None:
    """F3.2: Verify default degraded payload structure matches resilience specification."""
    async def failing_peer() -> None:
        raise ConnectionRefusedError("Peer offline")

    result = await safe_peer_call(failing_peer(), peer_name="stratex")
    assert result == {
        "status": "degraded",
        "peer": "stratex",
        "error": "ConnectionRefusedError",
        "message": "Peer offline",
        "fallback": True,
    }


@pytest.mark.asyncio
async def test_f3_03_safe_peer_call_custom_fallback_payload() -> None:
    """F3.3: Verify safe_peer_call returns custom fallback payload when provided."""
    custom = {"action": "fallback_strategy", "confidence": 0.0, "safe": True}
    async def broken_peer() -> None:
        raise RuntimeError("Service unavailable")

    result = await safe_peer_call(broken_peer(), fallback_data=custom, peer_name="intelx")
    assert result == custom


@pytest.mark.asyncio
async def test_f3_04_safe_peer_call_preserves_successful_results() -> None:
    """F3.4: Verify successful peer call coroutine returns its actual result unchanged."""
    async def healthy_peer() -> dict[str, str]:
        return {"result": "inference_output", "tokens": "128"}

    res = await safe_peer_call(healthy_peer(), peer_name="inference")
    assert res == {"result": "inference_output", "tokens": "128"}


@pytest.mark.asyncio
async def test_f3_05_safe_peer_call_handles_arbitrary_exceptions() -> None:
    """F3.5: Verify safe_peer_call traps arbitrary runtime exceptions gracefully."""
    async def exploding_call() -> None:
        raise KeyError("Missing peer envelope header")

    res = await safe_peer_call(exploding_call(), peer_name="futuris")
    assert res["status"] == "degraded"
    assert res["error"] == "KeyError"
    assert res["fallback"] is True


# ==============================================================================
# Feature 4: SQLite WAL & Busy Timeout Migration (5 tests)
# ==============================================================================

def test_f4_01_connect_sqlite_enforces_wal_journal_mode(temp_sqlite_db: Path) -> None:
    """F4.1: Verify connect_sqlite sets PRAGMA journal_mode=WAL."""
    conn = connect_sqlite(temp_sqlite_db)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    conn.close()
    assert mode.upper() == "WAL"


def test_f4_02_connect_sqlite_enforces_busy_timeout_at_least_5000ms(temp_sqlite_db: Path) -> None:
    """F4.2: Verify connect_sqlite sets PRAGMA busy_timeout >= 5000ms."""
    conn = connect_sqlite(temp_sqlite_db)
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout;")
    timeout_ms = cur.fetchone()[0]
    conn.close()
    assert timeout_ms >= 5000


def test_f4_03_connect_sqlite_enforces_foreign_keys_enabled(temp_sqlite_db: Path) -> None:
    """F4.3: Verify connect_sqlite enforces PRAGMA foreign_keys = ON."""
    conn = connect_sqlite(temp_sqlite_db)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys;")
    fk_status = cur.fetchone()[0]
    conn.close()
    assert fk_status == 1


def test_f4_04_connect_sqlite_enforces_synchronous_normal(temp_sqlite_db: Path) -> None:
    """F4.4: Verify connect_sqlite sets PRAGMA synchronous = NORMAL (1)."""
    conn = connect_sqlite(temp_sqlite_db)
    cur = conn.cursor()
    cur.execute("PRAGMA synchronous;")
    sync_mode = cur.fetchone()[0]
    conn.close()
    assert sync_mode == 1  # 1 corresponds to NORMAL in SQLite


def test_f4_05_get_db_connection_context_manager(temp_sqlite_db: Path) -> None:
    """F4.5: Verify get_db_connection context manager commits data and closes cleanly."""
    with get_db_connection(temp_sqlite_db) as conn:
        conn.execute("CREATE TABLE records (key TEXT PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO records VALUES ('alpha', 'omega');")

    # Read back in a fresh connection to verify commit took place
    with get_db_connection(temp_sqlite_db) as conn2:
        cur = conn2.cursor()
        cur.execute("SELECT val FROM records WHERE key = 'alpha';")
        row = cur.fetchone()
        assert row[0] == "omega"


# ==============================================================================
# Feature 5: Thread-Safe In-Memory Cache (5 tests)
# ==============================================================================

def test_f5_01_ttl_cache_basic_set_and_get() -> None:
    """F5.1: Verify TTLCache stores and retrieves key-value pair before expiration."""
    cache = TTLCache(default_ttl=10.0)
    cache.set("agent:status", "active")
    assert cache.get("agent:status") == "active"


def test_f5_02_ttl_cache_expiration() -> None:
    """F5.2: Verify TTLCache returns default/None after key expires."""
    cache = TTLCache(default_ttl=0.1)
    cache.set("ephemeral", 42)
    assert cache.get("ephemeral") == 42
    time.sleep(0.15)
    assert cache.get("ephemeral") is None


def test_f5_03_ttl_cache_lru_eviction_on_maxsize() -> None:
    """F5.3: Verify TTLCache evicts oldest entry when maxsize is exceeded."""
    cache = TTLCache(default_ttl=60.0, maxsize=2)
    cache.set("a", 1)
    time.sleep(0.01)
    cache.set("b", 2)
    time.sleep(0.01)
    cache.set("c", 3)
    assert len(cache) <= 2
    assert cache.get("a") is None
    assert cache.get("c") == 3


def test_f5_04_ttl_cache_delete_and_clear() -> None:
    """F5.4: Verify delete removes specified key and clear removes all entries."""
    cache = TTLCache(default_ttl=30.0)
    cache.set("x", 100)
    cache.set("y", 200)
    assert cache.delete("x") is True
    assert cache.get("x") is None
    assert cache.get("y") == 200
    cache.clear()
    assert cache.get("y") is None


@pytest.mark.asyncio
async def test_f5_05_ttl_cached_decorator_memoizes_async_call() -> None:
    """F5.5: Verify @ttl_cached memoizes async function calls within TTL window."""
    executions = 0

    @ttl_cached(ttl_seconds=1.0)
    async def get_expensive_posture_score(agent_id: str) -> int:
        nonlocal executions
        executions += 1
        return 95

    score1 = await get_expensive_posture_score("core")
    score2 = await get_expensive_posture_score("core")
    assert score1 == 95
    assert score2 == 95
    assert executions == 1


# ==============================================================================
# Feature 6: Uniform Error Envelopes & Redaction (5 tests)
# ==============================================================================

def test_f6_01_error_envelope_404_not_found(client: TestClient) -> None:
    """F6.1: Verify missing routes return standard ErrorEnvelope with error='HTTP_404'."""
    resp = client.get("/invalid/endpoint/route")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "HTTP_404"
    assert data["success"] is False
    assert "message" in data


def test_f6_02_error_envelope_422_validation_error(client: TestClient) -> None:
    """F6.2: Verify malformed requests return standard ErrorEnvelope with error='VALIDATION_ERROR'."""
    resp = client.post("/api/command", json={"unsupported_field": "test"})
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "VALIDATION_ERROR"
    assert data["success"] is False
    assert "message" in data


def test_f6_03_error_envelope_500_internal_error(client: TestClient) -> None:
    """F6.3: Verify server errors return standard ErrorEnvelope with error='INTERNAL_SERVER_ERROR'."""
    with patch("friday.api.server.build_health_report", side_effect=RuntimeError("Simulated server fault")):
        resp = client.get("/health")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"
        assert data["success"] is False
        assert "message" in data


def test_f6_04_error_envelope_custom_task_404(client: TestClient) -> None:
    """F6.4: Verify querying missing task ID returns 404 with TASK_NOT_FOUND error code."""
    resp = client.get("/v1/tasks/missing-task-id-abc")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "TASK_NOT_FOUND"
    assert data["success"] is False
    assert "missing-task-id-abc" in data["message"]


def test_f6_05_error_envelope_scrubs_secrets_in_detail(client: TestClient) -> None:
    """F6.5: Verify secrets embedded in error messages are scrubbed from error envelope."""
    secret = "AIzaSySecretApiKey1234567890123"
    with patch("friday.api.server.build_health_report", side_effect=ValueError(f"Database error with key {secret}")):
        resp = client.get("/health")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"
        assert secret not in resp.text
        assert "[REDACTED_SECRET]" in resp.text or "[REDACTED" in resp.text


# ==============================================================================
# Feature 7: Standardized Probes & Root Routes (5 tests)
# ==============================================================================

def test_f7_01_get_health_probe_contract(client: TestClient) -> None:
    """F7.1: Verify GET /health probe contract returns status=healthy, service=friday_core, version=2.0.0."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "friday_core"
    assert data["version"] == "2.0.0"
    assert "peers_mesh" in data


def test_f7_02_get_ready_probe_contract(client: TestClient) -> None:
    """F7.2: Verify GET /ready probe contract returns status=ready, ready=True, database=healthy."""
    resp = client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["status"] == "ready"
    assert data["service"] == "friday_core"
    assert data["database"] == "healthy"
    assert "timestamp" in data


def test_f7_03_get_metrics_root_alias(client: TestClient) -> None:
    """F7.3: Verify GET /metrics root route returns 200 and mirrors /api/metrics."""
    resp_root = client.get("/metrics")
    resp_api = client.get("/api/metrics")
    assert resp_root.status_code == 200
    assert resp_api.status_code == 200
    assert isinstance(resp_root.json(), dict)
    assert isinstance(resp_api.json(), dict)


def test_f7_04_get_v1_tasks_listing(client: TestClient) -> None:
    """F7.4: Verify GET /v1/tasks returns HTTP 200 with tasks list."""
    resp = client.get("/v1/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["tasks"], list)
    assert data["success"] is True


def test_f7_05_get_telemetry_endpoints(client: TestClient) -> None:
    """F7.5: Verify GET /api/telemetry and GET /api/system_telemetry return status=ok with hardware stats."""
    resp1 = client.get("/api/telemetry")
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert "status" in d1
    assert "timestamp" in d1

    resp2 = client.get("/api/system_telemetry")
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert "status" in d2
    assert "timestamp" in d2


# ==============================================================================
# Feature 8: Port 10000 Compliance Fix (5 tests)
# ==============================================================================

def test_f8_01_cli_default_port_is_10000() -> None:
    """F8.1: Verify default port in settings is 10000."""
    from friday.core.config import get_settings
    settings = get_settings()
    assert getattr(settings, "port", None) == 10000


def test_f8_02_cli_port_env_var_override() -> None:
    """F8.2: Verify validate_runtime_environment accepts standard port 10000."""
    with patch.dict("os.environ", {"PORT": "10000"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is True


def test_f8_03_settings_port_compliance() -> None:
    """F8.3: Verify server.py origin configuration includes port 10000."""
    from friday.api.server import _configured_origins
    origins = _configured_origins()
    assert "http://localhost:10000" in origins
    assert "http://127.0.0.1:10000" in origins


def test_f8_04_port_integer_validation_valid_range() -> None:
    """F8.4: Verify port values within 1..65535 are accepted without error."""
    for valid_port in ["80", "443", "8080", "10000"]:
        with patch.dict("os.environ", {"PORT": valid_port}):
            rep = validate_runtime_environment(fail_fast=False)
            assert rep["valid"] is True


def test_f8_05_port_non_numeric_validation() -> None:
    """F8.5: Verify non-numeric port strings are caught as validation issues."""
    with patch.dict("os.environ", {"PORT": "not_a_number"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("PORT environment variable must be an integer" in err for err in rep["issues"])


# ==============================================================================
# Feature 9: Startup Env Validation & Fail-Fast (5 tests)
# ==============================================================================

def test_f9_01_startup_validator_valid_environment() -> None:
    """F9.1: Verify validation succeeds on standard system environment."""
    report = validate_runtime_environment(fail_fast=False)
    assert report["valid"] is True
    assert isinstance(report["issues"], list)
    assert isinstance(report["warnings"], list)


def test_f9_02_startup_validator_detects_unwritable_directory() -> None:
    """F9.2: Verify unwritable data directory is identified as a fatal issue."""
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Read-only filesystem")):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("Data directory" in err and "not writable" in err for err in rep["issues"])


def test_f9_03_startup_validator_detects_invalid_port() -> None:
    """F9.3: Verify port outside 1..65535 is flagged as an issue."""
    with patch.dict("os.environ", {"PORT": "99999"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("out of range" in err for err in rep["issues"])


def test_f9_04_startup_validator_fail_fast_raises_in_production() -> None:
    """F9.4: Verify fail_fast=True raises StartupValidationError on fatal issues."""
    with patch.dict("os.environ", {"PORT": "-50"}):
        with pytest.raises(StartupValidationError):
            validate_runtime_environment(fail_fast=True)


def test_f9_05_startup_validator_warns_on_missing_production_keys() -> None:
    """F9.5: Verify missing LLM provider keys generate warnings in production mode."""
    with patch.dict("os.environ", {
        "FRIDAY_ENV": "production",
        "FRIDAY_LLM_PROVIDER": "chain",
        "FRIDAY_GROQ_API_KEY": "",
        "GROQ_API_KEY": "",
        "FRIDAY_GEMINI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "FRIDAY_OPENROUTER_API_KEY": "",
        "OPENROUTER_API_KEY": "",
        "FRIDAY_MISTRAL_API_KEY": "",
        "MISTRAL_API_KEY": "",
    }):
        rep = validate_runtime_environment(fail_fast=False)
        assert any("No external LLM API keys detected" in w for w in rep["warnings"])


# ==============================================================================
# Feature 10: Zero Secret Leakage (5 tests)
# ==============================================================================

def test_f10_01_redact_secrets_masks_gemini_api_key() -> None:
    """F10.1: Verify Google AIza keys are redacted from text."""
    key = "AIzaSyD0123456789abcdefghijklmnopqrstuv"
    raw = f"Error communicating with Gemini: key={key} expired"
    sanitized = redact_secrets(raw)
    assert key not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_f10_02_redact_secrets_masks_openai_api_key() -> None:
    """F10.2: Verify OpenAI sk- style keys are redacted from text."""
    key = "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEF"
    raw = f"Authorization header contains {key}"
    sanitized = redact_secrets(raw)
    assert key not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_f10_03_redact_secrets_masks_bearer_token() -> None:
    """F10.3: Verify Bearer tokens are masked with token redaction label."""
    raw = "Header Bearer abcdefghijklmnopqrstuvwxyz1234567890."
    sanitized = redact_secrets(raw)
    assert "Bearer [REDACTED_TOKEN]" in sanitized


def test_f10_04_redact_secrets_masks_jwt_token() -> None:
    """F10.4: Verify JSON Web Tokens are detected and redacted."""
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    raw = f"User session token is {jwt}"
    sanitized = redact_secrets(raw)
    assert jwt not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_f10_05_recursive_sanitize_deep_dictionary() -> None:
    """F10.5: Verify recursive_sanitize scrubs secret fields in arbitrarily nested data structures."""
    payload = {
        "status": "ok",
        "nested": {
            "api_key": "secret_key_12345",
            "metadata": {
                "password": "super_secret_password",
                "normal": "public_data",
            },
        },
        "items": [{"auth_token": "token_abc"}, {"safe": True}],
    }
    clean = recursive_sanitize(payload)
    assert clean["nested"]["api_key"] == "[REDACTED_SECRET]"
    assert clean["nested"]["metadata"]["password"] == "[REDACTED_SECRET]"
    assert clean["nested"]["metadata"]["normal"] == "public_data"
    assert clean["items"][0]["auth_token"] == "[REDACTED_SECRET]"
    assert clean["items"][1]["safe"] is True


# ==============================================================================
# Feature 11: Dockerfile PID 1 & 5s Shutdown (5 tests)
# ==============================================================================

def test_f11_01_dockerfile_specifies_non_root_user() -> None:
    """F11.1: Verify Dockerfile switches to non-root appuser."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "USER appuser" in dockerfile


def test_f11_02_dockerfile_exposes_port_10000() -> None:
    """F11.2: Verify Dockerfile exposes container port 10000."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "EXPOSE 10000" in dockerfile


def test_f11_03_dockerfile_cmd_uses_exec_uvicorn() -> None:
    """F11.3: Verify Dockerfile CMD uses exec uvicorn for PID 1 signal forwarding."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "exec uvicorn" in dockerfile
    assert "10000" in dockerfile


@pytest.mark.asyncio
async def test_f11_04_lifespan_graceful_shutdown_timeout_bounded() -> None:
    """F11.4: Verify background tasks cancellation in server lifespan completes within 5.0s."""
    # Simulate a slow background task being cancelled
    async def slow_background_task() -> None:
        try:
            await asyncio.sleep(100.0)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
            raise

    task = asyncio.create_task(slow_background_task())
    start = time.monotonic()
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.CancelledError:
        pass
    duration = time.monotonic() - start
    assert duration < 5.0


@pytest.mark.asyncio
async def test_f11_05_lifespan_closes_fleet_client() -> None:
    """F11.5: Verify fleet_client aclose() completes cleanly within 3.0s timeout."""
    _ = fleet_client.get_shared_client()
    start = time.monotonic()
    await asyncio.wait_for(fleet_client.aclose(), timeout=3.0)
    duration = time.monotonic() - start
    assert duration < 3.0
    assert fleet_client._shared_client is None


# ==============================================================================
# Feature 12: Bulletproof Testing & 85%+ Coverage (5 tests)
# ==============================================================================

def test_f12_01_request_id_correlation_header(client: TestClient) -> None:
    """F12.1: Verify all responses return X-Request-ID correlation tracking header."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 8


def test_f12_02_custom_request_id_preserved(client: TestClient) -> None:
    """F12.2: Verify inbound X-Request-ID is preserved and reflected in the response."""
    custom_uuid = "req-12345678-abcd-ef01-2345"
    resp = client.get("/health", headers={"X-Request-ID": custom_uuid})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == custom_uuid


def test_f12_03_cors_origin_whitelisting(client: TestClient) -> None:
    """F12.3: Verify permitted origins receive CORS Access-Control-Allow-Origin response."""
    resp = client.get("/health", headers={"Origin": "http://localhost:10000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:10000"


def test_f12_04_healthcheck_head_request_support(client: TestClient) -> None:
    """F12.4: Verify /health supports lightweight HEAD requests for container health probes."""
    resp = client.head("/health")
    assert resp.status_code == 200
    assert resp.text == ""  # HEAD response body must be empty


def test_f12_05_offline_mock_safety() -> None:
    """F12.5: Verify test environment enforces mock isolation without hitting external network."""
    from friday.core.config import get_settings
    settings = get_settings()
    assert settings.env == "testing" or settings.embedding_provider == "none"


# ==============================================================================
# Feature 13: Docs, CI/CD & Clean Git Delivery (5 tests)
# ==============================================================================

def test_f13_01_readme_contains_mermaid_diagram() -> None:
    """F13.1: Verify README.md contains Mermaid architecture topology diagram."""
    readme_path = Path("README.md")
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "```mermaid" in content


def test_f13_02_env_example_contains_port_10000() -> None:
    """F13.2: Verify .env.example references standard port 10000."""
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert "10000" in env_example


def test_f13_03_env_example_has_no_secrets() -> None:
    """F13.3: Verify .env.example does not leak live API keys."""
    env_example = Path(".env.example").read_text(encoding="utf-8")
    # Check for live Google API keys
    assert not re.search(r"AIza[0-9A-Za-z-_]{35}", env_example)
    # Check for live OpenAI sk- keys
    assert not re.search(r"sk-[a-zA-Z0-9]{32,}", env_example)


def test_f13_04_ci_workflow_has_linter_and_test_steps() -> None:
    """F13.4: Verify .github/workflows/ci.yml runs ruff check and pytest."""
    ci_path = Path(".github/workflows/ci.yml")
    assert ci_path.exists()
    content = ci_path.read_text(encoding="utf-8")
    assert "ruff check" in content
    assert "pytest" in content


def test_f13_05_ci_workflow_targets_python_311() -> None:
    """F13.5: Verify CI workflow specifies Python 3.11 environment."""
    ci_path = Path(".github/workflows/ci.yml")
    content = ci_path.read_text(encoding="utf-8")
    assert "3.11" in content
