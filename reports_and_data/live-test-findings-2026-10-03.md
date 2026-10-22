# Live fleet test findings — 2026-10-03

Honest state of the nine-agent FRIDAY Universe, measured against **live Render
cloud HTTP**, not sandboxes.

## 1. Headline

| Probe run | Pass | Fail | Cause |
|---|---|---|---|
| First run (`ac6a581b7255`) | 4 | 12 | 3 bugs in my own probe |
| Second run (`1306bab9c1a5`) | 6 | 10 | probe bugs fixed |
| Third run (`45a2fc6d7d34`, current) | **7** | **9** | one more probe bug fixed (below) |

**All 9 remaining failures have one root cause: the nine inter-agent mesh API
keys are unset in Render.** Not one of them is an agent defect.

### Probe bug found and fixed this run
`Stratex reports its open paper positions` was probing `/positions` and getting
a 404. Live verification showed the real route is `/api/positions`
(`{"count":0,"data_age":0.0,"filter":"OPEN","positions":[],"status":"SUCCESS"}`)
and `/positions` is genuinely 404 on the deployed router. My earlier note had
the two backwards. The probe is corrected; this is why the count moved 6 -> 7.

## 2. What is genuinely working (proven against live cloud)

- **Inference** — generates real text through a real provider
  (`HTTP 200`, ~1.9s) and serves its model panel. Proof that the Render
  dashboard secret path works: `NVIDIA_API_KEY` is already set there.
- **IntelX** — starts a real research job over the network (`HTTP 202`) and
  serves its configured news sources.
- **Futuris** — serves its real calibration accuracy.
- **Stratex** — analyses a real symbol and stays paper-only (`HTTP 200`),
  real Binance websocket, 16 symbols, real `/api/status`.
- **`/health` on all nine services** returns `200`.

## 3. What is blocked, and the exact live error

| Agent | Probe result | Live error string |
|---|---|---|
| Forge | 503 x2 | `service_auth_unconfigured` — "A unique FORGE_API_KEY is required." |
| Sentinel | 503 x2 | "A unique SENTINEL_API_KEY is required." |
| Cortex | 401 / 503 | "Insecure or placeholder credentials rejected in production." |
| Memora | 401 x2 | "Invalid agent credentials" |
| Futuris | 503 | "Fresh Stratex volatility and drawdown telemetry are required." |

Futuris is the only *downstream* failure: it refuses to forecast from
placeholder telemetry, which is correct behaviour, not a bug.

### The security guards are working. The deployment is misconfigured.
Every agent rejects the literal documentation placeholders (`forge_api`,
`memora_api`, `sentinel_api`, `inference_api`, `stratex_api`, `intelx_api`,
`futuris_api`, `cortex_api`, `friday_api`). Each `render.yaml` correctly declares
its secrets `sync: false`, which means **Render prompts for them in the
dashboard and never received a value.** The agents refusing to trust a
placeholder is the system working.

## 4. Defects found and fixed (each with a test that fails without the fix)

1. **Stratex health lied about being able to trade.** `get_engine_health_data()`
   computed health from process liveness only, so an engine that was alive but
   holding no executable strategy reported `components.strategy: "OK"` and
   `overall_health: "OK"`. Added `trading_capable` + `capability_reasons`
   (`NO_EXECUTABLE_STRATEGY`, `NO_STRATEGY_EVALUATION`,
   `STALE_STRATEGY_EVALUATION`, `UNREADABLE_EVALUATION_TIMESTAMP`). `/ready`
   now requires liveness **and** capability. 10 regression tests in
   `Stratex/tests/test_engine_capability_truthfulness.py`; 7 fail if reverted.
2. **Memora could not start.** `no such column: event_log.target_agent` — the
   migration chain tried to `create_table` a table that already existed, so
   `create_all()` had built it from a stale ORM model and no `ALTER` ever ran.
   Both event-feed migrations are now convergent. Memora now boots cleanly.
   8 tests in `Memora/tests/test_event_feed_migrations_converge.py`; 6 fail if
   reverted.
3. **Six Render/Docker config defects:** Inference `--workers 4` on a 512MB free
   tier; Memora never ran migrations at boot; Cortex set `DATABASE_URL` which
   nothing reads (the real setting is `postgres_dsn` -> `POSTGRES_DSN`); three
   relative sqlite paths that resolve against whatever cwd uvicorn inherits;
   Inference missing `HOST`; **Sentinel's `.env` was tracked in GitHub** (values
   verified to be the known placeholders — no real credential ever leaked).
   Covered by 94 checks in `tests/test_render_blueprints.py`; 6 fail if reverted.

## 5. Regression baselines (re-run with changes stashed, to prove no regressions)

| Suite | Baseline | With my changes |
|---|---|---|
| Stratex | 6 failed / 991 passed | 6 failed / **1001 passed** |
| Memora | 1 failed / 153 passed | 1 failed / **161 passed** |
| Universe cross-agent | 115 passed, 24 skipped | unchanged |
| Cortex / IntelX / Inference / Sentinel / blueprints | 205 / 179+2 / 20 / all / 94 | unchanged |

## 6. THE ONE THING YOU HAVE TO DO — Render dashboard secrets

Nothing else is worth doing first. This single step is what turns 7/16 into
16/16.

### Why it is 81 values and not 9
Every service calls all eight peers, and each peer verifies the caller's
identity by key. So **each of the nine services needs all nine keys** — nine
*distinct* secrets, pasted into nine dashboards.

### Step 1 — generate nine distinct keys

```bash
python -c "import secrets;[print(n+'_API_KEY='+secrets.token_urlsafe(32)) for n in ['FRIDAY','INFERENCE','MEMORA','STRATEX','INTELX','FUTURIS','CORTEX','FORGE','SENTINEL']]"
```

Keep that output. Each key **must be different** — several agents reject
credentials that are reused across services, and that check is deliberate.

### Step 2 — paste all nine into every service
Render dashboard -> each service -> **Environment** -> add each of these nine
keys with the same value you generated:

```
FRIDAY_API_KEY      INFERENCE_API_KEY   MEMORA_API_KEY
STRATEX_API_KEY     INTELX_API_KEY      FUTURIS_API_KEY
CORTEX_API_KEY      FORGE_API_KEY       SENTINEL_API_KEY
```

### Step 3 — per-service extras

| Service | Also set |
|---|---|
| **FRIDAY** | `FRIDAY_UNIVERSE_API_KEY` (new, distinct), `FRIDAY_GEMINI_API_KEY`, `FRIDAY_LLM_API_KEY` |
| **Inference** | `NVIDIA_API_KEY` (already working), `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` |
| **Memora** | `TURSO_AUTH_TOKEN` (from your Turso dashboard) |
| **IntelX** | `TURSO_AUTH_TOKEN` (from your Turso dashboard) |
| **Cortex** | `JWT_SECRET` |
| **Stratex** | `TRADING_BOT_API_KEY_READ`, `TRADING_BOT_API_KEY_CONTROL` (both new and distinct), `BOT_API_KEY`, `API_KEY` + `SECRET_KEY` (Binance **testnet** only) |
| **Futuris** | `FUTURIS_FRIDAY_API_KEY` = the `FRIDAY_API_KEY` value |
| **Sentinel** | `SENTINEL_FRIDAY_API_KEY` = the `FRIDAY_API_KEY` value, plus `SENTINEL_CAPABILITY_SIGNING_KEY` and `SENTINEL_AUDIT_SIGNING_KEY` |

Never paste a secret value into `render.yaml` — that file is in GitHub. It stays
`sync: false`.

### Step 4 — commit, then let Render rebuild
My fixes are **uncommitted in the working tree**. Render builds from GitHub, so
nothing I fixed reaches cloud until it is committed and pushed. Nothing has been
pushed yet.

### Step 5 — verify
```bash
cd "D:/FRIDAY Universe/FRIDAY" && python research/live_fleet_functional_probe.py
```
Expect 16/16. If anything still fails, the printed live error string tells you
which key is still wrong.

## 7. What is NOT done (stated plainly)

- **Nothing is committed or pushed.** 6 repos have uncommitted fixes.
- **Stratex has 6 pre-existing position-recovery failures** I deliberately left
  alone: `test_recovery.py::test_reconstruct_active_trades`,
  `test_state_reconciliation.py` (naked position not OCO-protected, orphan order
  not cancelled), `test_equity_accounting_anti_double_counting.py`,
  `test_final_accounting_audit.py::test_k_l_no_duplicate_recovery_accounting`,
  `test_paper_shadow_memora.py::test_missing_key_fails_closed_before_transport`.
  These matter more than anything else left, because Stratex places real orders.
- **Sentinel's audit ledger is not durable.** `SENTINEL_STORAGE_BACKEND=memory`
  means the hash chain dies on every redeploy while `/health` still reports
  `audit_chain_valid: true`. That is the same class of lie as the Stratex health
  bug and is not yet fixed.
- **Voice / wake-word / desktop control unverified** — needs ~20 minutes at the
  laptop with a microphone.
- **`sqlalchemy-libsql` cannot install on this Windows box** (no 3.11 wheel,
  source build needs Rust), so local Memora runs the SQLite fallback. Cloud is
  unaffected — live health reports `event_store_durable: true`.