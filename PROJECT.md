# Project: FRIDAY Core Gateway Tier-1 Upgrade

## Architecture
FRIDAY Core Gateway is the central API gateway and holographic core of the FRIDAY Universe agent mesh running on Oracle Cloud Always Free (ARM64 Ampere A1). It exposes REST and FastMCP endpoints (port 10000) for clients, delegates commands to cognitive planning and autonomous engines, coordinates with 8 specialized mesh peer services (`cortex`, `forge`, `futuris`, `inference`, `intelx`, `memora`, `sentinel`, `stratex`), and persists state to local SQLite databases.

### Core Architecture Pillars:
- **Async Resilience Layer**: Centralized `httpx.AsyncClient` connection pooling with explicit timeouts, wrapped with `AsyncCircuitBreaker` (states: CLOSED, OPEN, HALF_OPEN), exponential backoff with randomized jitter, and `safe_peer_call` graceful degradation.
- **SQLite Storage Foundation**: Unified `friday.core.database.connect_sqlite` enforcing `PRAGMA journal_mode=WAL;`, `PRAGMA busy_timeout=5000;`, `PRAGMA foreign_keys=ON;`, and `PRAGMA synchronous=NORMAL;` across all 12 database connection sites.
- **In-Memory Caching**: High-throughput thread-safe `TTLCache` (with `threading.RLock`, TTL expiration, LRU eviction) applied to telemetry endpoints and expensive asset registry calculations.
- **Strict Contract Hardening**: Enforced Pydantic `ErrorEnvelope` schemas (`{"error": "<error_code>", "message": "<human_readable_detail>", "success": false}`) on all error responses, catch-all 500 handler, standard `/health`, `/ready` (with disk space check), root `/metrics`, and `/v1/tasks` endpoints.
- **Security & Governance**: Startup environment validation with fail-fast in production, automated secret redaction (`redact_secrets()`) across all error envelopes and logs, non-root `appuser` (UID 1000) with `exec` PID 1 signal forwarding for 5-second graceful shutdown.
- **Verification & Testing**: Bulletproof route integration test suite covering 200, 400, 404, 503 paths, achieving >=85% core gateway coverage, clean `ruff` linting, and hardened CI/CD.

---

## Feature Inventory
Every feature from the Survey phase appears here with its assigned milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Async Client Pooling | Replace ad-hoc `httpx.AsyncClient` instances in `mesh.py`, `fleet_client.py`, `ai_universe_client.py`, and `repair_trigger.py` with pooled client and explicit timeout configurations. | M1 | Survey (Explorer 2) |
| 2 | Circuit Breakers & Retries with Jitter | Wire `src/friday/core/resilience.py` (`AsyncCircuitBreaker`, `retry_with_backoff` with jitter) into mesh and peer client calls. | M1 | Survey (Explorer 2) |
| 3 | Graceful Degradation on Timeouts | Implement `safe_peer_call` fallbacks returning structured degraded responses rather than unhandled 500 errors on peer timeouts. | M1 | Survey (Explorer 2) |
| 4 | SQLite WAL & Busy Timeout Migration | Migrate all direct `sqlite3.connect()` calls across 10 repository files to `friday.core.database.connect_sqlite` (`PRAGMA journal_mode=WAL;`, `PRAGMA busy_timeout=5000;`). | M1 | Survey (Explorer 2) |
| 5 | Thread-Safe In-Memory Cache | Apply `@ttl_cached` from `friday.core.cache` to `/api/telemetry`, `/api/system_telemetry`, and `AssetRegistry.calculate_security_posture_score()`. | M1 | Survey (Explorer 2) |
| 6 | Uniform Error Envelopes & Redaction | Enforce Pydantic `ErrorEnvelope` (`{"error": ..., "message": ..., "success": false}`) and register exception handlers (`Exception`, `FridayError`, `HTTPException`, `RequestValidationError`) with secret scrubbing. | M2 | Survey (Explorer 1 & 3) |
| 7 | Standardized Probes & Root Routes | Standardize `/health`, implement disk space and mesh check in `/ready`, add root `/metrics` alias, and implement `/v1/tasks` listing & standard 404 response. | M2 | Survey (Explorer 1) |
| 8 | Port 10000 Compliance Fix | Fix hardcoded fallback port `9000` in `src/friday/cli/main.py:374, 645` to default to `10000` / `settings.port`. | M2 | Survey (Explorer 1) |
| 9 | Startup Env Validation & Fail-Fast | Expand `startup_validator.py` (`PORT`, `FRIDAY_ENV`, directory permissions) and enable `fail_fast=True` in production mode in `server.py:182` with pointers to `.env.example`. | M3 | Survey (Explorer 3) |
| 10 | Zero Secret Leakage | Enforce `redact_secrets()` on all exception messages, error envelopes, and extend logging scrubber to root and uvicorn loggers. | M3 | Survey (Explorer 3) |
| 11 | Dockerfile PID 1 & 5s Shutdown | Fix `Dockerfile:61` to use `exec uvicorn ...`; bound lifespan teardown within 5.0 seconds maximum; cleanup proactive monitoring thread on shutdown. | M3 | Survey (Explorer 1 & 3) |
| 12 | Bulletproof Testing & 85%+ Coverage | Expand unit and route integration tests covering 200/400/404/503 paths for core routes, achieve >=85% code coverage, 100% portable test pass rate. | M4 | Survey (Explorer 3) |
| 13 | Docs, CI/CD & Clean Git Delivery | Update `README.md`, clean up `.env.example` (add `PORT=10000`, remove duplicate keys), update CI workflow (pip cache, coverage enforcement), commit and push to `origin/main`. | M5 | Survey (Explorer 3) |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Architecture & Async Resilience | Features 1, 2, 3, 4, 5 (Async client pooling, circuit breakers with jitter, safe_peer_call, SQLite WAL + busy_timeout=5000ms migration, TTLCache application) | none | IN_PROGRESS |
| M2 | Contract Hardening & Service Telemetry | Features 6, 7, 8 (Pydantic ErrorEnvelope, exception handlers, /health, /ready with disk check, root /metrics, /v1/tasks, port 10000 CLI fix) | M1 | PLANNED |
| M3 | Security & Resource Governance | Features 9, 10, 11 (Startup fail-fast validation, automated secret scrubbing across envelopes & logs, Dockerfile exec PID 1, 5s lifespan teardown ceiling) | M2 | PLANNED |
| M4 | Bulletproof Testing & 85%+ Coverage | Feature 12 (Core gateway route integration tests covering 200/400/404/503 paths, pass 100% of portable tests, achieve >=85% coverage) | M3, TEST_READY | PLANNED |
| M5 | Documentation, CI/CD & Delivery | Feature 13 (README.md, .env.example cleanup, CI workflow hardening, commit and push to origin/main) | M4 | PLANNED |

---

## Interface Contracts

### 1. Unified Error Envelope
All REST API failure responses must adhere strictly to:
```json
{
  "error": "<UPPERCASE_SNAKE_OR_HTTP_CODE>",
  "message": "<human_readable_detail_with_secrets_redacted>",
  "success": false
}
```
HTTP Status Codes:
- `400`: `VALIDATION_ERROR` (Invalid request body, query parameter, or malformed payload)
- `404`: `NOT_FOUND` (Resource, route, or task ID not found)
- `503`: `SERVICE_UNAVAILABLE` or `PEER_TIMEOUT` (Upstream mesh peer failure, circuit breaker open)
- `500`: `INTERNAL_SERVER_ERROR` (Uncaught server exception)

### 2. Standard Endpoints
- `GET /health` -> `200 OK`: `{"status": "healthy", "service": "friday_core", "version": "2.0.0"}`
- `GET /ready` -> `200 OK` (or `503`): `{"status": "ready", "checks": {"database": "ok", "disk_space": "ok", "mesh": "ok"}}`
- `GET /metrics` & `GET /api/metrics` -> `200 OK`: diagnostic Prometheus or process telemetry metrics.
- `GET /api/telemetry` -> `200 OK`: cached process uptime, CPU, memory, request counters.
- `GET /v1/tasks` -> `200 OK`: list recent tasks. `GET /v1/tasks/{task_id}` -> `200 OK` or `404 Not Found` with standard error envelope.

### 3. Database Connection Helper
All SQLite connections must go through:
```python
from friday.core.database import connect_sqlite

conn = connect_sqlite(db_path)
# Enforces:
# PRAGMA journal_mode = WAL;
# PRAGMA busy_timeout = 5000;
# PRAGMA foreign_keys = ON;
# PRAGMA synchronous = NORMAL;
```

### 4. Circuit Breaker & Resilience
All outbound peer calls to specialist agents must use:
```python
from friday.core.resilience import safe_peer_call, retry_with_backoff, AsyncCircuitBreaker

result = await safe_peer_call(
    coro_func,
    fallback_response={"status": "degraded", "error": "PEER_TIMEOUT", "success": False},
    circuit_breaker=circuit_breaker,
)
```

### 5. In-Memory Cache
```python
from friday.core.cache import ttl_cached, TTLCache

@ttl_cached(ttl_seconds=2.0, max_size=128)
async def get_system_telemetry(): ...
```

---

## Code Layout

- `src/friday/api/server.py` — FastAPI application, routes, lifespan, exception handlers.
- `src/friday/core/resilience.py` — `AsyncCircuitBreaker`, `retry_with_backoff`, `safe_peer_call`.
- `src/friday/core/database.py` — SQLite WAL & busy timeout connection helper (`connect_sqlite`).
- `src/friday/core/cache.py` — Thread-safe `TTLCache` and `@ttl_cached` decorator.
- `src/friday/core/startup_validator.py` — Startup environment variable validation & diagnostics.
- `src/friday/security/scrubber.py` — Secret scrubbing and automated redaction (`redact_secrets`).
- `src/friday/cognition/mesh.py` — Inter-agent mesh communication client.
- `src/friday/ecosystem/fleet_client.py` — Fleet status and peer agent client.
- `src/friday/cli/main.py` — CLI entry point and server runner.
- `Dockerfile` — Container definition (non-root `appuser`, port 10000, `exec uvicorn`).
- `.env.example` — Authoritative environment variables documentation.
- `tests/test_tier1_resilience_and_contracts.py` — Tier-1 contract, resilience, and route tests.
- `tests/e2e/` — Opaque-box E2E test suites (Tiers 1-4).
- `README.md` — Authoritative project documentation and Mermaid architecture diagram.
- `.github/workflows/ci.yml` — GitHub Actions CI pipeline.
