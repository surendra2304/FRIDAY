"""Test suite verifying Tier-1 production resilience, contracts, SQLite WAL mode, and telemetry."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from friday.api.server import app
from friday.core.cache import TTLCache, ttl_cached
from friday.core.database import connect_sqlite, get_db_connection
from friday.core.resilience import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    retry_with_backoff,
    safe_peer_call,
)
from friday.core.startup_validator import validate_runtime_environment


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_health_endpoint_contract(client: TestClient) -> None:
    """Verify /health returns HTTP 200 with service, version, and health status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "friday_core"
    assert data["version"] == "2.0.0"
    assert data["overall"] == "healthy"
    assert "observed_at" in data
    assert data["peers_mesh"] == "connected"


def test_ready_endpoint_contract(client: TestClient, tmp_path: Path) -> None:
    """Verify /ready probe returns HTTP 200 and checks SQLite storage."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["status"] == "ready"
    assert data["service"] == "friday_core"
    assert data["database"] == "healthy"
    assert "timestamp" in data


def test_ready_endpoint_degraded_storage(client: TestClient) -> None:
    """Verify /ready returns 503 when storage layer fails."""
    with patch("friday.api.server.connect_sqlite", side_effect=sqlite3.OperationalError("Disk full")):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False
        assert data["status"] == "not_ready"
        assert "unhealthy" in data["database"]


def test_standardized_error_envelopes(client: TestClient) -> None:
    """Verify 404 and 422 return standardized error envelopes."""
    # 404 Not Found
    resp_404 = client.get("/nonexistent/api/path")
    assert resp_404.status_code == 404
    data_404 = resp_404.json()
    assert data_404["error"] == "HTTP_404"
    assert data_404["success"] is False
    assert "message" in data_404

    # 422 Validation Error
    resp_422 = client.post("/api/command", json={"invalid_field": 123})
    assert resp_422.status_code == 422
    data_422 = resp_422.json()
    assert data_422["error"] == "VALIDATION_ERROR"
    assert data_422["success"] is False


def test_correlation_id_tracking(client: TestClient) -> None:
    """Verify X-Request-ID propagation and generation."""
    # Custom request ID preserved
    custom_id = "test-req-id-12345"
    resp = client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == custom_id

    # Auto-generated request ID when header omitted
    resp2 = client.get("/health")
    assert resp2.status_code == 200
    assert "X-Request-ID" in resp2.headers
    assert len(resp2.headers["X-Request-ID"]) > 10


def test_ttl_cache_operations() -> None:
    """Verify TTLCache set, get, expiry, and maxsize eviction."""
    cache = TTLCache(default_ttl=0.2, maxsize=2)
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    assert cache.get("k1") == "v1"
    assert cache.get("k2") == "v2"

    # Eviction on exceeding maxsize
    cache.set("k3", "v3")
    assert len(cache) <= 2

    # Expiry
    time.sleep(0.25)
    assert cache.get("k1") is None
    assert cache.get("k2") is None


@pytest.mark.asyncio
async def test_ttl_cached_decorator() -> None:
    """Verify @ttl_cached decorator caches calls."""
    call_count = 0

    @ttl_cached(ttl_seconds=1.0)
    async def compute(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2

    val1 = await compute(5)
    val2 = await compute(5)
    assert val1 == 10
    assert val2 == 10
    assert call_count == 1


def test_sqlite_wal_and_busy_timeout(tmp_path: Path) -> None:
    """Verify SQLite connections enable busy_timeout and WAL mode."""
    db_file = tmp_path / "test.db"
    conn = connect_sqlite(db_file, timeout=3.0)
    cursor = conn.cursor()

    cursor.execute("PRAGMA busy_timeout;")
    timeout_row = cursor.fetchone()
    assert timeout_row[0] >= 5000

    cursor.execute("PRAGMA foreign_keys;")
    fk_row = cursor.fetchone()
    assert fk_row[0] == 1

    cursor.execute("PRAGMA journal_mode;")
    mode_row = cursor.fetchone()
    assert mode_row[0].upper() == "WAL"
    conn.close()

    # Context manager test
    with get_db_connection(db_file) as ctx_conn:
        ctx_conn.execute("CREATE TABLE test_data (id INT);")
        ctx_conn.execute("INSERT INTO test_data VALUES (42);")

    with get_db_connection(db_file) as ctx_conn:
        cur = ctx_conn.cursor()
        cur.execute("SELECT id FROM test_data;")
        assert cur.fetchone()[0] == 42


@pytest.mark.asyncio
async def test_async_circuit_breaker() -> None:
    """Verify AsyncCircuitBreaker state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    breaker = AsyncCircuitBreaker(
        service_name="test_service",
        failure_threshold=2,
        recovery_time_seconds=0.1,
        half_open_success_threshold=1,
    )
    assert breaker.state == CircuitState.CLOSED

    # Record 2 failures -> trips to OPEN
    await breaker.record_failure(ValueError("fail 1"))
    assert breaker.state == CircuitState.CLOSED
    await breaker.record_failure(ValueError("fail 2"))
    assert breaker.state == CircuitState.OPEN

    # While OPEN, call fails fast
    with pytest.raises(CircuitBreakerOpenError):
        async def dummy() -> None:
            pass
        await breaker.call(dummy)

    # After recovery time, allows probe and transitions to HALF_OPEN
    await asyncio.sleep(0.15)
    assert await breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN

    # Success heals circuit back to CLOSED
    await breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_retry_with_backoff_and_jitter() -> None:
    """Verify retry_with_backoff retries and succeeds."""
    attempts = 0

    @retry_with_backoff(retries=3, base_delay=0.01, max_delay=0.05, jitter=True)
    async def flaky_task() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("Temporary glitch")
        return "success"

    result = await flaky_task()
    assert result == "success"
    assert attempts == 3


@pytest.mark.asyncio
async def test_safe_peer_call_graceful_degradation() -> None:
    """Verify safe_peer_call catches exceptions and returns fallback payload."""
    async def failing_peer() -> None:
        raise TimeoutError("Peer timeout")

    outcome = await safe_peer_call(failing_peer(), peer_name="cortex")
    assert outcome["status"] == "degraded"
    assert outcome["peer"] == "cortex"
    assert outcome["fallback"] is True
    assert "TimeoutError" in outcome["error"]


def test_startup_validation(tmp_path: Path) -> None:
    """Verify pre-flight validation succeeds in normal environment."""
    from friday.core.startup_validator import StartupValidationError

    with patch.dict("os.environ", {"FRIDAY_DATA_DIR": str(tmp_path)}):
        report = validate_runtime_environment(fail_fast=False)
        assert report["valid"] is True
        assert isinstance(report["warnings"], list)

    # Fail fast on unwritable directory
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
        with pytest.raises(StartupValidationError):
            validate_runtime_environment(fail_fast=True)


def test_ttl_cache_edge_cases() -> None:
    """Verify TTLCache delete, clear, and sync decorator."""
    cache = TTLCache(default_ttl=60.0)
    cache.set("a", 1)
    assert cache.delete("a") is True
    assert cache.delete("nonexistent") is False

    cache.set("b", 2)
    cache.clear()
    assert cache.get("b") is None

    # Sync ttl_cached
    sync_calls = 0

    @ttl_cached(ttl_seconds=10.0)
    def sync_compute(n: int) -> int:
        nonlocal sync_calls
        sync_calls += 1
        return n + 10

    assert sync_compute(5) == 15
    assert sync_compute(5) == 15
    assert sync_calls == 1


@pytest.mark.asyncio
async def test_retry_exhaustion_and_circuit_half_open_failure() -> None:
    """Verify retry decorator raises after max retries and circuit half-open failure trips to OPEN."""
    @retry_with_backoff(retries=2, base_delay=0.01, jitter=False)
    async def always_fails() -> None:
        raise RuntimeError("Definite failure")

    with pytest.raises(RuntimeError):
        await always_fails()

    # Breaker in HALF_OPEN fails -> immediately trips to OPEN
    breaker = AsyncCircuitBreaker(recovery_time_seconds=0.05)
    await breaker.record_failure()
    breaker.state = CircuitState.HALF_OPEN
    await breaker.record_failure(RuntimeError("Probe failed"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_fleet_client_circuit_breaker_blocks_dispatch() -> None:
    """Verify fleet_client blocks dispatch_task when target agent's circuit breaker is OPEN."""
    from friday.core.task_envelope import TaskEnvelope, TaskStatus
    from friday.ecosystem.fleet_client import fleet_client

    breaker = fleet_client.get_circuit_breaker("cortex")
    breaker.state = CircuitState.OPEN
    breaker.last_failure_time = time.monotonic()

    envelope = TaskEnvelope(
        task_id="test-task-1",
        source_agent="friday",
        target_agent="cortex",
        action="reason",
        payload={"query": "mesh test"},
    )

    res = await fleet_client.dispatch_task(envelope)
    assert res.status == TaskStatus.BLOCKED
    assert "Circuit breaker for peer 'cortex' is OPEN" in str(res.error)

    # Healing breaker allows dispatch attempt
    await breaker.record_success()
    breaker.state = CircuitState.CLOSED


def test_telemetry_ttl_caching(client: TestClient) -> None:
    """Verify /api/telemetry and /api/system_telemetry return cached responses within TTL window."""
    resp1 = client.get("/api/telemetry")
    assert resp1.status_code == 200
    t1 = resp1.json().get("timestamp")

    resp2 = client.get("/api/telemetry")
    assert resp2.status_code == 200
    t2 = resp2.json().get("timestamp")
    assert t1 == t2  # Cached hit within 2.0s

    sys_resp1 = client.get("/api/system_telemetry")
    assert sys_resp1.status_code == 200
    st1 = sys_resp1.json().get("timestamp")

    sys_resp2 = client.get("/api/system_telemetry")
    assert sys_resp2.status_code == 200
    st2 = sys_resp2.json().get("timestamp")
    assert st1 == st2


def test_memora_wal_mode(tmp_path: Path) -> None:
    """Verify MemoraClient initializes local database with SQLite WAL journal mode."""
    from friday.memory.memora_client import MemoraClient
    import sqlite3

    db_path = str(tmp_path / "memora_test.db")
    _ = MemoraClient(local_db_path=db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    conn.close()

    assert mode.upper() == "WAL"


def test_metrics_root_alias(client: TestClient) -> None:
    """Verify /metrics root endpoint acts as an alias to /api/metrics."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_v1_tasks_endpoints(client: TestClient) -> None:
    """Verify /v1/tasks listing and standardized 404 error envelope on missing task."""
    resp_list = client.get("/v1/tasks")
    assert resp_list.status_code == 200
    data_list = resp_list.json()
    assert data_list["status"] == "ok"
    assert isinstance(data_list["tasks"], list)

    resp_404 = client.get("/v1/tasks/nonexistent-task-999")
    assert resp_404.status_code == 404
    data_404 = resp_404.json()
    assert data_404["error"] == "TASK_NOT_FOUND"
    assert data_404["success"] is False
    assert "nonexistent-task-999" in data_404["message"]


def test_error_envelope_secret_scrubbing(client: TestClient) -> None:
    """Verify secrets are redacted in error messages."""
    fake_key = "AIzaSyFakeSecretKeyForTesting12345"
    resp = client.get(f"/nonexistent-route-with-secret?key={fake_key}")
    assert resp.status_code == 404
    body = resp.text
    assert fake_key not in body


def test_startup_validator_port_checking() -> None:
    """Verify validate_runtime_environment detects invalid PORT values."""
    with patch.dict("os.environ", {"PORT": "invalid_not_number"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("PORT environment variable must be an integer" in issue for issue in rep["issues"])

    with patch.dict("os.environ", {"PORT": "99999"}):
        rep2 = validate_runtime_environment(fail_fast=False)
        assert rep2["valid"] is False
        assert any("out of range" in issue for issue in rep2["issues"])



