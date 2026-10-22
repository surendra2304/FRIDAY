# FRIDAY Core Gateway Test Infrastructure Specification (TEST_INFRA.md)

## 1. Test Philosophy & Architecture

The FRIDAY Core Gateway test infrastructure is built upon an **opaque-box, requirement-driven, hermetic testing methodology**. Tests are derived directly from user requirements (`ORIGINAL_REQUEST.md`) and authoritative interface specifications (`PROJECT.md § Interface Contracts`), operating strictly against public service contracts and observable behavior without coupling to internal private implementations.

### Core Testing Principles:
1. **Opaque-Box Integrity**: Tests exercise the service exclusively through public APIs, HTTP routes, CLI entry points, and documented public library interfaces.
2. **Authoritative Expected Output Derivation**: All assertions verify explicit contract schemas (e.g. `ErrorEnvelope`, `/health`, `/ready`), deterministic state transitions, and HTTP status codes defined in `PROJECT.md`.
3. **Hermetic Isolation**: Tests execute fully offline without dependencies on external cloud APIs, hardware peripherals, or pre-existing database files. Every test provisions its own ephemeral environment and cleans up after itself.
4. **Adversarial & Boundary Rigor**: The test suite actively challenges the gateway with malformed payloads, out-of-range ports, expired tokens, concurrent database writes, circuit trips, and secret injection to prove zero secret leakage and guaranteed graceful degradation.

---

## 2. Test Directory Layout

```
d:/FRIDAY Universe/FRIDAY/
├── TEST_INFRA.md                     # This test infrastructure specification
├── TEST_READY.md                     # Test execution verification and readiness summary
└── tests/
    ├── conftest.py                   # Global pytest fixtures and isolation hooks
    ├── test_tier1_resilience_and_contracts.py  # Baseline contract and resilience unit tests
    └── e2e/                          # Comprehensive Opaque-Box E2E Test Suite
        ├── __init__.py               # E2E test package marker
        ├── conftest.py               # E2E-specific fixtures (TestClient, mock peers, isolated DBs)
        ├── test_tier1_features.py    # Tier 1: Feature Coverage (>=5 tests per feature, 13 features)
        ├── test_tier2_boundaries.py  # Tier 2: Boundary & Corner Cases (>=5 tests per feature, 13 features)
        ├── test_tier3_combinations.py# Tier 3: Cross-Feature Pairwise Combinations
        └── test_tier4_scenarios.py   # Tier 4: Real-World Multi-Step Application Scenarios
```

---

## 3. 4-Tier Test Suite Hierarchy

| Tier | Category | Scope | Requirement | Target Count |
|---|---|---|---|---|
| **Tier 1** | **Feature Coverage** | Isolated happy-path and contract verification covering all 13 features in `PROJECT.md § Feature Inventory`. | >= 5 tests per feature | >= 65 tests |
| **Tier 2** | **Boundary & Corner Cases** | Edge cases, malformed payloads, 400 validation, 404 not found, 503 timeouts, out-of-range ports, missing env vars. | >= 5 tests per feature | >= 65 tests |
| **Tier 3** | **Cross-Feature Combinations** | Pairwise interaction testing (e.g. error envelope + secret scrubbing; SQLite WAL concurrency; circuit breaker + graceful degradation). | Pairwise coverage matrix | >= 10 tests |
| **Tier 4** | **Real-World Scenarios** | Multi-step end-to-end user and system workflows (Gateway boot, health check, command execution, telemetry, task cancellation, shutdown). | Realistic system flows | >= 5 scenarios |

---

## 4. Feature Inventory Coverage Matrix

| # | Feature Name | Tier 1 Tests (Feature) | Tier 2 Tests (Boundary) | Tier 3 (Pairwise) | Tier 4 (Scenario) |
|---|---|---|---|---|---|
| **F1** | Async Client Pooling | `test_f1_*` (5 tests) | `test_f1_b_*` (5 tests) | Pairwise #3 | Scenario #3 |
| **F2** | Circuit Breakers & Retries with Jitter | `test_f2_*` (5 tests) | `test_f2_b_*` (5 tests) | Pairwise #3 | Scenario #3 |
| **F3** | Graceful Degradation on Timeouts | `test_f3_*` (5 tests) | `test_f3_b_*` (5 tests) | Pairwise #3 | Scenario #3 |
| **F4** | SQLite WAL & Busy Timeout Migration | `test_f4_*` (5 tests) | `test_f4_b_*` (5 tests) | Pairwise #2 | Scenario #4 |
| **F5** | Thread-Safe In-Memory Cache | `test_f5_*` (5 tests) | `test_f5_b_*` (5 tests) | Pairwise #4 | Scenario #4 |
| **F6** | Uniform Error Envelopes & Redaction | `test_f6_*` (5 tests) | `test_f6_b_*` (5 tests) | Pairwise #1, #5 | Scenario #5 |
| **F7** | Standardized Probes & Root Routes | `test_f7_*` (5 tests) | `test_f7_b_*` (5 tests) | Pairwise #4, #6 | Scenario #1, #2 |
| **F8** | Port 10000 Compliance Fix | `test_f8_*` (5 tests) | `test_f8_b_*` (5 tests) | Pairwise #5 | Scenario #1 |
| **F9** | Startup Env Validation & Fail-Fast | `test_f9_*` (5 tests) | `test_f9_b_*` (5 tests) | Pairwise #5 | Scenario #1 |
| **F10** | Zero Secret Leakage | `test_f10_*` (5 tests) | `test_f10_b_*` (5 tests) | Pairwise #1, #4 | Scenario #5 |
| **F11** | Dockerfile PID 1 & 5s Shutdown | `test_f11_*` (5 tests) | `test_f11_b_*` (5 tests) | Pairwise #6 | Scenario #1 |
| **F12** | Bulletproof Testing & 85%+ Coverage | `test_f12_*` (5 tests) | `test_f12_b_*` (5 tests) | Pairwise #6 | Scenario #4, #5 |
| **F13** | Docs, CI/CD & Clean Git Delivery | `test_f13_*` (5 tests) | `test_f13_b_*` (5 tests) | Full Suite | Full Suite |

---

## 5. Test Runner & Execution Commands

### Run Full E2E Test Suite:
```bash
python -m pytest tests/e2e/ -v
```

### Run by Specific Tier:
```bash
# Tier 1: Feature Coverage
python -m pytest tests/e2e/test_tier1_features.py -v

# Tier 2: Boundary & Corner Cases
python -m pytest tests/e2e/test_tier2_boundaries.py -v

# Tier 3: Cross-Feature Combinations
python -m pytest tests/e2e/test_tier3_combinations.py -v

# Tier 4: Real-World Scenarios
python -m pytest tests/e2e/test_tier4_scenarios.py -v
```

### Run Full Offline / Portable Test Suite:
```bash
python -m pytest tests/e2e/ tests/test_tier1_resilience_and_contracts.py -v -m "not live and not hardware and not windows"
```

---

## 6. Fixtures & Isolation Protocol

- **`client`**: FastAPI `TestClient` initialized with `raise_server_exceptions=False` to ensure all 4xx/5xx responses pass through standard exception handlers and produce uniform error envelopes.
- **`async_client`**: `httpx.AsyncClient` bound to the ASGI application for testing asynchronous endpoints, streaming, and concurrency.
- **`temp_sqlite_db`**: Pytest fixture generating unique temporary SQLite files for each test using `tmp_path`, guaranteeing zero cross-test interference and verifying WAL mode pragmas.
- **`isolated_env`**: Fixture cleanly mocking and resetting environment variables (`PORT`, `FRIDAY_ENV`, `FRIDAY_DATA_DIR`, API keys) before and after each test.
- **`mock_peer_mesh`**: Fixture simulating peer agent responses (`cortex`, `memora`, `forge`) under healthy, timeout, and degraded conditions.
