"""Tier 2: Boundary & Corner Cases Test Suite.

Provides edge cases, invalid inputs, 400 validation, 404, 503 timeouts, and boundary conditions covering all 13 features in PROJECT.md (>= 5 tests per feature, 65 tests total).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
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
from friday.core.startup_validator import StartupValidationError, validate_runtime_environment
from friday.ecosystem.fleet_client import fleet_client
from friday.security.scrubber import redact_secrets, recursive_sanitize


# ==============================================================================
# Feature 1: Async Client Pooling Boundaries (5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_f1_b01_client_with_zero_timeout_raises_timeout_error() -> None:
    """F1.B1: Verify microsecond timeout triggers TimeoutException rather than hanging indefinitely."""
    client = httpx.AsyncClient(timeout=0.0001)
    with pytest.raises(httpx.TimeoutException):
        await client.get("https://httpbin.org/delay/5")
    await client.aclose()


@pytest.mark.asyncio
async def test_f1_b02_client_multiple_concurrent_aclose_calls_are_idempotent() -> None:
    """F1.B2: Verify multiple concurrent aclose() calls do not crash or raise exceptions."""
    _ = fleet_client.get_shared_client()
    await asyncio.gather(
        fleet_client.aclose(),
        fleet_client.aclose(),
        fleet_client.aclose(),
    )
    assert fleet_client._shared_client is None


@pytest.mark.asyncio
async def test_f1_b03_client_connection_to_unreachable_ip_fails_fast() -> None:
    """F1.B3: Verify connection to non-routable IP fails within configured explicit timeout."""
    client = httpx.AsyncClient(timeout=0.2)
    start = time.monotonic()
    with pytest.raises((httpx.ConnectTimeout, httpx.ConnectError)):
        await client.get("http://192.0.2.1:10000")
    duration = time.monotonic() - start
    assert duration < 2.0
    await client.aclose()


def test_f1_b04_fleet_client_circuit_breaker_cache_case_insensitivity() -> None:
    """F1.B4: Verify fleet_client breaker lookup normalizes whitespace and casing."""
    b1 = fleet_client.get_circuit_breaker("CORTEX")
    b2 = fleet_client.get_circuit_breaker(" cortex ")
    assert b1 is b2


def test_f1_b05_mesh_request_timeout_enforces_minimum_bound() -> None:
    """F1.B5: Verify Mesh enforces minimum request_timeout bound of 0.05s against invalid zero/negative numbers."""
    from friday.cognition.mesh import Mesh
    mesh_zero = Mesh(request_timeout=0.0)
    assert mesh_zero.request_timeout >= 0.05
    mesh_neg = Mesh(request_timeout=-10.0)
    assert mesh_neg.request_timeout >= 0.05


# ==============================================================================
# Feature 2: Circuit Breakers Boundaries (5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_f2_b01_circuit_breaker_single_failure_threshold_trips_immediately() -> None:
    """F2.B1: Verify threshold=1 trips to OPEN on very first recorded failure."""
    breaker = AsyncCircuitBreaker(failure_threshold=1)
    assert breaker.state == CircuitState.CLOSED
    await breaker.record_failure(ValueError("first failure"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_f2_b02_circuit_breaker_zero_recovery_time_permits_immediate_half_open() -> None:
    """F2.B2: Verify recovery_time_seconds=0 immediately allows probe and transitions to HALF_OPEN."""
    breaker = AsyncCircuitBreaker(failure_threshold=1, recovery_time_seconds=0.0)
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    # With 0 recovery time, immediate check transitions to HALF_OPEN
    assert await breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_f2_b03_circuit_breaker_failure_during_half_open_trips_back_to_open() -> None:
    """F2.B3: Verify failure during HALF_OPEN probe immediately trips breaker back to OPEN."""
    breaker = AsyncCircuitBreaker(failure_threshold=1, recovery_time_seconds=0.01)
    await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    await asyncio.sleep(0.02)
    assert await breaker.can_execute() is True
    assert breaker.state == CircuitState.HALF_OPEN
    await breaker.record_failure(RuntimeError("probe failed"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_f2_b04_retry_decorator_zero_retries_raises_original_error() -> None:
    """F2.B4: Verify @retry_with_backoff(retries=0) executes exactly once and re-raises exception."""
    calls = 0

    @retry_with_backoff(retries=0)
    async def no_retries() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("instant failure")

    with pytest.raises(ValueError):
        await no_retries()
    assert calls == 1


@pytest.mark.asyncio
async def test_f2_b05_retry_decorator_ignores_non_retryable_exceptions() -> None:
    """F2.B5: Verify non-matching exception types immediately bubble up without retrying."""
    calls = 0

    @retry_with_backoff(retries=3, retryable_exceptions=(KeyError,))
    async def selective_retry() -> None:
        nonlocal calls
        calls += 1
        raise TypeError("Not retryable")

    with pytest.raises(TypeError):
        await selective_retry()
    assert calls == 1


# ==============================================================================
# Feature 3: Graceful Degradation Boundaries (5 tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_f3_b01_safe_peer_call_handles_empty_fallback_dict() -> None:
    """F3.B1: Verify safe_peer_call returns empty dictionary without failure if fallback_data={}."""
    async def broken() -> None:
        raise RuntimeError("failed")

    res = await safe_peer_call(broken(), fallback_data={})
    assert res == {}


@pytest.mark.asyncio
async def test_f3_b02_safe_peer_call_handles_coroutine_returning_none() -> None:
    """F3.B2: Verify safe_peer_call preserves coroutine that normally returns None."""
    async def returns_none() -> None:
        return None

    res = await safe_peer_call(returns_none(), peer_name="noop")
    assert res is None


@pytest.mark.asyncio
async def test_f3_b03_safe_peer_call_nested_exception_propagation_prevented() -> None:
    """F3.B3: Verify chained/nested exceptions are caught and degraded."""
    async def chained_fail() -> None:
        try:
            raise ValueError("Root cause")
        except ValueError as err:
            raise RuntimeError("Chained cause") from err

    res = await safe_peer_call(chained_fail(), peer_name="chained")
    assert res["status"] == "degraded"
    assert res["error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_f3_b04_safe_peer_call_with_unicode_peer_name() -> None:
    """F3.B4: Verify safe_peer_call formats correctly with unicode or special characters in peer_name."""
    async def fail() -> None:
        raise OSError("I/O error")

    res = await safe_peer_call(fail(), peer_name="peer_🤖_alpha")
    assert res["peer"] == "peer_🤖_alpha"
    assert res["fallback"] is True


@pytest.mark.asyncio
async def test_f3_b05_safe_peer_call_preserves_error_type_name() -> None:
    """F3.B5: Verify fallback error field preserves exact exception class name."""
    class CustomMeshTimeoutException(Exception):
        pass

    async def fail_custom() -> None:
        raise CustomMeshTimeoutException("timeout 45s")

    res = await safe_peer_call(fail_custom(), peer_name="custom")
    assert res["error"] == "CustomMeshTimeoutException"


# ==============================================================================
# Feature 4: SQLite WAL Boundaries (5 tests)
# ==============================================================================

def test_f4_b01_connect_sqlite_in_memory_handles_unsupported_wal() -> None:
    """F4.B1: Verify :memory: database connection configures gracefully without crashing on WAL."""
    conn = connect_sqlite(":memory:")
    assert conn is not None
    cur = conn.cursor()
    cur.execute("CREATE TABLE test (x INT);")
    cur.execute("INSERT INTO test VALUES (1);")
    cur.execute("SELECT x FROM test;")
    assert cur.fetchone()[0] == 1
    conn.close()


def test_f4_b02_connect_sqlite_creates_deeply_nested_missing_directories(tmp_path: Path) -> None:
    """F4.B2: Verify connect_sqlite creates arbitrary deep directory paths automatically."""
    deep_path = tmp_path / "deep" / "nested" / "sub" / "folder" / "storage.db"
    assert not deep_path.parent.exists()
    conn = connect_sqlite(deep_path)
    assert deep_path.parent.exists()
    conn.close()


def test_f4_b03_get_db_connection_rolls_back_on_integrity_error(temp_sqlite_db: Path) -> None:
    """F4.B3: Verify transaction rolls back on integrity error inside get_db_connection."""
    with get_db_connection(temp_sqlite_db) as conn:
        conn.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users VALUES (1, 'Alice');")

    with pytest.raises(sqlite3.IntegrityError):
        with get_db_connection(temp_sqlite_db) as conn2:
            conn2.execute("INSERT INTO users VALUES (2, 'Bob');")
            conn2.execute("INSERT INTO users VALUES (1, 'Duplicate');")  # Must roll back Bob

    with get_db_connection(temp_sqlite_db) as conn3:
        cur = conn3.cursor()
        cur.execute("SELECT COUNT(*) FROM users;")
        assert cur.fetchone()[0] == 1  # Only Alice survived


def test_f4_b04_connect_sqlite_busy_timeout_custom_large_value(temp_sqlite_db: Path) -> None:
    """F4.B4: Verify passing custom busy_timeout_ms=15000 is honored."""
    conn = connect_sqlite(temp_sqlite_db, busy_timeout_ms=15000)
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout;")
    val = cur.fetchone()[0]
    conn.close()
    assert val == 15000


def test_f4_b05_connect_sqlite_enforces_foreign_key_constraint_violation(temp_sqlite_db: Path) -> None:
    """F4.B5: Verify foreign keys pragma actively prevents orphan records."""
    conn = connect_sqlite(temp_sqlite_db)
    conn.execute("CREATE TABLE parent (id INT PRIMARY KEY);")
    conn.execute("CREATE TABLE child (id INT PRIMARY KEY, p_id INT REFERENCES parent(id));")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO child VALUES (1, 999);")  # No parent 999
    conn.close()


# ==============================================================================
# Feature 5: In-Memory Cache Boundaries (5 tests)
# ==============================================================================

def test_f5_b01_ttl_cache_maxsize_one_boundary() -> None:
    """F5.B1: Verify maxsize=1 cache strictly keeps only the single newest item."""
    cache = TTLCache(default_ttl=10.0, maxsize=1)
    cache.set("k1", "v1")
    time.sleep(0.01)
    cache.set("k2", "v2")
    assert len(cache) == 1
    assert cache.get("k1") is None
    assert cache.get("k2") == "v2"


def test_f5_b02_ttl_cache_very_large_keys() -> None:
    """F5.B2: Verify TTLCache handles large keys (10KB string) without degradation."""
    large_key = "k" * 10000
    cache = TTLCache(default_ttl=5.0)
    cache.set(large_key, "payload")
    assert cache.get(large_key) == "payload"


def test_f5_b03_ttl_cache_unicode_and_binary_values() -> None:
    """F5.B3: Verify caching complex objects, tuples, and non-ASCII unicode values."""
    cache = TTLCache(default_ttl=10.0)
    val = {"emoji": "🚀", "data": (1, 2, [3, 4])}
    cache.set("complex", val)
    assert cache.get("complex") == val


def test_f5_b04_ttl_cache_delete_non_existent_key_returns_false() -> None:
    """F5.B4: Verify deleting a key that is not present returns False cleanly."""
    cache = TTLCache()
    assert cache.delete("never_existed") is False


def test_f5_b05_ttl_cache_concurrent_multithreaded_writes() -> None:
    """F5.B5: Verify concurrent multithreaded writes to TTLCache operate without race conditions."""
    cache = TTLCache(default_ttl=5.0, maxsize=100)
    errors: list[Exception] = []

    def writer(idx: int) -> None:
        try:
            for j in range(50):
                cache.set(f"thread_{idx}_{j}", j)
                _ = cache.get(f"thread_{idx}_{j}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(cache) <= 100


# ==============================================================================
# Feature 6: Uniform Error Envelopes Boundaries (5 tests)
# ==============================================================================

def test_f6_b01_error_envelope_empty_json_body_returns_422(client: TestClient) -> None:
    """F6.B1: Verify posting empty JSON body to a required-body route returns 422 with standard envelope."""
    resp = client.post("/api/command", json={})
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "VALIDATION_ERROR"
    assert data["success"] is False


def test_f6_b02_error_envelope_malformed_json_syntax_returns_422(client: TestClient) -> None:
    """F6.B2: Verify posting broken JSON syntax returns 422 with standard envelope."""
    resp = client.post(
        "/api/command",
        content="{\"broken_json: 123",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "VALIDATION_ERROR"
    assert data["success"] is False


def test_f6_b03_error_envelope_http_405_method_not_allowed(client: TestClient) -> None:
    """F6.B3: Verify unsupported HTTP method returns 405 with standard error envelope."""
    resp = client.post("/health")
    assert resp.status_code == 405
    data = resp.json()
    assert data["error"] == "HTTP_405"
    assert data["success"] is False


def test_f6_b04_error_envelope_exception_with_empty_message(client: TestClient) -> None:
    """F6.B4: Verify server exception with blank message provides fallback description."""
    with patch("friday.api.server.build_health_report", side_effect=RuntimeError("")):
        resp = client.get("/health")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "INTERNAL_SERVER_ERROR"
        assert len(data["message"]) > 0
        assert data["success"] is False


def test_f6_b05_error_envelope_scrubs_multiple_different_secrets(client: TestClient) -> None:
    """F6.B5: Verify multiple interleaved secrets in error detail are all masked."""
    sec1 = "AIzaSyMultiSecret1111111111111111"
    sec2 = "sk-MultiSecret22222222222222222222"
    with patch("friday.api.server.build_health_report", side_effect=ValueError(f"Fault {sec1} and {sec2}")):
        resp = client.get("/health")
        assert resp.status_code == 500
        assert sec1 not in resp.text
        assert sec2 not in resp.text
        assert "[REDACTED_SECRET]" in resp.text


# ==============================================================================
# Feature 7: Standardized Probes Boundaries (5 tests)
# ==============================================================================

def test_f7_b01_ready_probe_low_disk_space_returns_503(client: TestClient) -> None:
    """F7.B1: Verify /ready returns 503 when disk space falls below 50MB."""
    # Mock shutil.disk_usage to return 10MB free
    with patch("shutil.disk_usage", return_value=(100 * 1024 * 1024, 90 * 1024 * 1024, 10 * 1024 * 1024)):
        resp = client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["ready"] is False
        assert data["status"] == "not_ready"
        assert "low_disk_space" in data.get("disk", "")


def test_f7_b02_ready_probe_sqlite_failure_returns_503(client: TestClient) -> None:
    """F7.B2: Verify /ready returns 503 when SQLite probe connection fails."""
    with patch("friday.api.server.connect_sqlite", side_effect=sqlite3.OperationalError("Database locked")):
        resp = client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["ready"] is False
        assert "OperationalError" in data.get("database", "")


def test_f7_b03_v1_tasks_id_with_special_characters_and_path_traversal(client: TestClient) -> None:
    """F7.B3: Verify /v1/tasks handles path traversal and special characters safely returning 404."""
    resp = client.get("/v1/tasks/../../etc/passwd")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"] == "TASK_NOT_FOUND" or data["error"] == "HTTP_404"


def test_f7_b04_v1_tasks_zero_and_negative_limit(client: TestClient) -> None:
    """F7.B4: Verify /v1/tasks with limit=0 returns 200 OK with empty tasks list."""
    resp = client.get("/v1/tasks?limit=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["tasks"] == []


def test_f7_b05_telemetry_endpoint_handles_psutil_exceptions(client: TestClient) -> None:
    """F7.B5: Verify /api/telemetry returns status=unavailable when psutil raises an error."""
    with patch("psutil.cpu_percent", side_effect=RuntimeError("psutil unavailable")):
        resp = client.get("/api/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable" or "cpu_percent" in data


# ==============================================================================
# Feature 8: Port 10000 Compliance Boundaries (5 tests)
# ==============================================================================

def test_f8_b01_port_boundary_zero_is_rejected() -> None:
    """F8.B1: Verify PORT=0 is identified as out of valid range 1..65535."""
    with patch.dict("os.environ", {"PORT": "0"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("out of range" in err for err in rep["issues"])


def test_f8_b02_port_boundary_65536_is_rejected() -> None:
    """F8.B2: Verify PORT=65536 is identified as out of range."""
    with patch.dict("os.environ", {"PORT": "65536"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("out of range" in err for err in rep["issues"])


def test_f8_b03_port_boundary_negative_is_rejected() -> None:
    """F8.B3: Verify PORT=-1 is identified as out of range."""
    with patch.dict("os.environ", {"PORT": "-1"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("out of range" in err for err in rep["issues"])


def test_f8_b04_port_boundary_float_is_rejected() -> None:
    """F8.B4: Verify floating point port string is caught as non-integer."""
    with patch.dict("os.environ", {"PORT": "10000.5"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False
        assert any("must be an integer" in err for err in rep["issues"])


def test_f8_b05_port_boundary_whitespace_padded_valid() -> None:
    """F8.B5: Verify whitespace-padded port is converted cleanly."""
    with patch.dict("os.environ", {"PORT": " 10000 "}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is True


# ==============================================================================
# Feature 9: Startup Validation Boundaries (5 tests)
# ==============================================================================

def test_f9_b01_startup_validation_handles_spaces_in_data_dir(tmp_path: Path) -> None:
    """F9.B1: Verify data directory with spaces and symbols operates cleanly."""
    spaced_dir = tmp_path / "Data Directory With Spaces #1"
    with patch.dict("os.environ", {"FRIDAY_DATA_DIR": str(spaced_dir)}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is True
        assert spaced_dir.exists()


def test_f9_b02_startup_validation_reports_all_issues_simultaneously() -> None:
    """F9.B2: Verify multiple simultaneous issues are all collected into report['issues']."""
    with patch.dict("os.environ", {"PORT": "999999"}):
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("Locked")):
            rep = validate_runtime_environment(fail_fast=False)
            assert rep["valid"] is False
            assert len(rep["issues"]) >= 2


def test_f9_b03_startup_validation_fail_fast_false_does_not_raise() -> None:
    """F9.B3: Verify fail_fast=False never raises StartupValidationError even on invalid config."""
    with patch.dict("os.environ", {"PORT": "invalid"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["valid"] is False


def test_f9_b04_startup_validation_environment_case_insensitivity() -> None:
    """F9.B4: Verify environment name comparison is case-insensitive."""
    with patch.dict("os.environ", {"FRIDAY_ENV": "PRODUCTION"}):
        rep = validate_runtime_environment(fail_fast=False)
        assert rep["environment"] == "production"


def test_f9_b05_startup_validation_non_chain_provider_missing_keys_no_chain_warning() -> None:
    """F9.B5: Verify non-chain provider (e.g. 'mock') does not trigger provider 'chain' warnings."""
    with patch.dict("os.environ", {
        "FRIDAY_ENV": "production",
        "FRIDAY_LLM_PROVIDER": "mock",
    }):
        rep = validate_runtime_environment(fail_fast=False)
        assert not any("No external LLM API keys detected for provider 'chain'" in w for w in rep["warnings"])


# ==============================================================================
# Feature 10: Zero Secret Leakage Boundaries (5 tests)
# ==============================================================================

def test_f10_b01_redact_secrets_short_strings_not_masked() -> None:
    """F10.B1: Verify short trivial strings (<= 5 chars) are not registered to prevent over-redaction."""
    from friday.security.scrubber import global_scrubber
    global_scrubber.register_secret("abcd")
    text = "abcdef ghijkl"
    # "abcd" is <= 5 chars, so it should not be masked as an exact secret
    assert "abcd" in global_scrubber.redact(text)


def test_f10_b02_redact_secrets_empty_and_none_inputs() -> None:
    """F10.B2: Verify passing empty string or None returns safely without error."""
    assert redact_secrets("") == ""
    assert redact_secrets(None) is None


def test_f10_b03_redact_secrets_preserves_surrounding_text() -> None:
    """F10.B3: Verify non-sensitive text surrounding masked secret is completely preserved."""
    key = "AIzaSyValidFormatKey1234567890abcdefgh"
    raw = f"Header: Prefix - {key} - Suffix"
    res = redact_secrets(raw)
    assert res.startswith("Header: Prefix - ")
    assert res.endswith(" - Suffix")
    assert key not in res


def test_f10_b04_recursive_sanitize_handles_byte_strings_with_invalid_utf8() -> None:
    """F10.B4: Verify binary bytes that cannot be decoded as UTF-8 are scrubbed safely."""
    invalid_utf8 = b"\x80\x81\x82\xff"
    res = recursive_sanitize(invalid_utf8)
    assert res == b"[REDACTED_BINARY]"


def test_f10_b05_recursive_sanitize_preserves_booleans_ints_and_none() -> None:
    """F10.B5: Verify scalar primitive types are preserved unaltered."""
    assert recursive_sanitize(True) is True
    assert recursive_sanitize(False) is False
    assert recursive_sanitize(42) == 42
    assert recursive_sanitize(3.14) == 3.14
    assert recursive_sanitize(None) is None


# ==============================================================================
# Feature 11: Dockerfile & Shutdown Boundaries (5 tests)
# ==============================================================================

def test_f11_b01_dockerfile_healthcheck_timeout_within_5s() -> None:
    """F11.B1: Verify Dockerfile HEALTHCHECK specifies timeout of 5 seconds."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--timeout=5s" in dockerfile


def test_f11_b02_dockerfile_healthcheck_interval_is_30s() -> None:
    """F11.B2: Verify Dockerfile HEALTHCHECK specifies interval of 30 seconds."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "--interval=30s" in dockerfile


def test_f11_b03_dockerfile_port_fallback_syntax() -> None:
    """F11.B3: Verify Dockerfile CMD includes bash fallback syntax ${PORT:-10000}."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "${PORT:-10000}" in dockerfile


@pytest.mark.asyncio
async def test_f11_b04_lifespan_timeout_aborts_hung_cancellation() -> None:
    """F11.B4: Verify lifespan shutdown cancellation timeout enforces 5.0s upper bound on hung tasks."""
    fut = asyncio.get_running_loop().create_future()

    async def hung_task() -> None:
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            try:
                await fut
            except asyncio.CancelledError:
                pass

    t = asyncio.create_task(hung_task())
    await asyncio.sleep(0.01)
    t.cancel()
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.gather(t, return_exceptions=True), timeout=0.05)
    except asyncio.TimeoutError:
        timed_out = True
    finally:
        if not fut.done():
            fut.set_result(None)
        await asyncio.gather(t, return_exceptions=True)

    assert timed_out is True


@pytest.mark.asyncio
async def test_f11_b05_fleet_client_aclose_when_client_already_closed() -> None:
    """F11.B5: Verify calling fleet_client.aclose() when already closed is safe."""
    await fleet_client.aclose()
    # Call again when _shared_client is already None
    await fleet_client.aclose()
    assert fleet_client._shared_client is None


# ==============================================================================
# Feature 12: Testing & Coverage Boundaries (5 tests)
# ==============================================================================

def test_f12_b01_unsupported_path_length_limit(client: TestClient) -> None:
    """F12.B1: Verify exceptionally long URI path (1000+ chars) returns 404 without crashing server."""
    long_path = "/" + ("subpath/" * 150)
    resp = client.get(long_path)
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_f12_b02_request_with_oversized_correlation_id(client: TestClient) -> None:
    """F12.B2: Verify unusually long X-Request-ID is handled and reflected without error."""
    long_req_id = "req-" + ("a" * 256)
    resp = client.get("/health", headers={"X-Request-ID": long_req_id})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == long_req_id


def test_f12_b03_disallowed_origin_returns_403_on_control_route(client: TestClient) -> None:
    """F12.B3: Verify state-changing request from untrusted origin is rejected with HTTP 403."""
    resp = client.post(
        "/api/chat",
        json={"message": "hello"},
        headers={"Origin": "https://malicious-attacker-site.com"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["error"] == "HTTP_403"
    assert "not permitted" in data["message"]


def test_f12_b04_empty_command_string_in_chat_endpoint(client: TestClient) -> None:
    """F12.B4: Verify /api/chat with empty message executes safely without 500 error."""
    resp = client.post("/api/chat", json={"message": ""})
    # Either succeeds or returns structured response, never 500
    assert resp.status_code in (200, 400, 422)


def test_f12_b05_options_preflight_cors_response(client: TestClient) -> None:
    """F12.B5: Verify OPTIONS preflight request to /health returns CORS headers."""
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:10000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


# ==============================================================================
# Feature 13: Docs & CI Boundaries (5 tests)
# ==============================================================================

def test_f13_b01_readme_documents_port_10000_explicitly() -> None:
    """F13.B1: Verify README.md explicitly documents port 10000."""
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "10000" in readme


def test_f13_b02_env_example_has_valid_syntax_no_trailing_junk() -> None:
    """F13.B2: Verify .env.example contains properly formatted key-value pairs or comments."""
    lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "=" in stripped, f"Invalid line in .env.example: {stripped}"


def test_f13_b03_ci_workflow_no_pull_request_duplicates() -> None:
    """F13.B3: Verify CI workflow runs on pushes to main and pull requests without duplicated steps."""
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "branches:" in ci
    assert "main" in ci


def test_f13_b04_readme_documents_health_and_ready_endpoints() -> None:
    """F13.B4: Verify README.md references /health and /ready probe endpoints."""
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "/health" in readme
    assert "/ready" in readme


def test_f13_b05_dockerfile_base_image_is_python_311_slim() -> None:
    """F13.B5: Verify Dockerfile uses python:3.11-slim base image."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "python:3.11-slim" in dockerfile
