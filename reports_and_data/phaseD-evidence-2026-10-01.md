# Phase D — Truth in the cloud: evidence record

**Date of record:** 2026-10-02 · **Owner:** Surendra · **Prime rule:** evidence or it didn't happen.

Everything below was produced by a command whose output is quoted verbatim. Where a
step could not be completed, it is listed as blocked with the exact owner action
named, and **no result is simulated, inferred, or written down as if it happened**.

---

## D1 — Live health payloads match current code

### D1.1 The defect the audit found

A sweep of all nine live services was compared against the code in each local
checkout. Seven matched. **Two services were running builds older than their own
codebase**: Memora and Cortex. Both drifted *before* the Phase C pushes, so neither
had ever been redeployed since.

The drift was not merely cosmetic, and fixing it correctly required finding out
*which* handler actually answers the probe.

### D1.2 Real defect: the Cortex health fix would have gone to dead code

The first pass added the evidence fields to `main.py`'s health handler. Probing the
running app locally showed the canonical probe never reaches it:

```
GET  /health {'status': 'UP', 'timestamp': ..., 'service': 'CORTEX API'}
GET  /v1/health {'status': 'healthy', 'service': ..., 'environment': 'development', 'timestamp': ...}
```

`main.py` registers `@app.api_route("/health")` at line 110, but
`app.include_router(production_router)` runs at line 58. Starlette matches routes in
registration order, so `production_router.liveness_probe()` answers `/health` and the
`main.py` handler is **unreachable dead code**. This matches the live payload exactly:

```
=== LIVE cortex /health ===
{"status":"UP","timestamp":"2026-10-02T04:40:57.675771","service":"CORTEX API"}
=== LIVE cortex /v1/health ===
{"status":"healthy","service":"CORTEX API","environment":"production","timestamp":"2026-10-02T04:40:58.012039"}
```

A patch written from reading the code alone would have shipped, passed CI, and changed
nothing an operator can see. The fix was moved to the handler that actually answers,
and the dead route was removed rather than left as a trap for the next reader.

### D1.3 Second real defect: `HEAD /health` was rejected

Adding a `HEAD` regression test surfaced a second gap — the app returned **405** for
`HEAD /health`, because neither probe route declared the method. Fixed rather than
weakened the test:

```
HEAD /health -> 200        (was 405)
HEAD /health/ready -> 503  (was 405; 503 is the honest readiness answer here)
```

Note for accuracy: the live service already answers `HEAD /health` with **200**,
measured `curl -o /dev/null -w "%{http_code}" -I` → `200`. The Render edge proxy
normalises `HEAD` to `GET`, so the 405 was masked in production and only visible at
the application. The server-side gap is real; it was simply invisible from outside.

### D1.4 Code changes shipped

| Repo | Commit | Change | CI on that head |
|---|---|---|---|
| IntelX | `9e719ae` | `healthz` gains `evidence_class: process_liveness` + `observed_at`; `readyz` gains `dependency_readiness` + `observed_at`; legacy `timestamp` reuses the same instant | ✅ `success` (46s) |
| Cortex | `dfb37ab` | Evidence fields added to the handler that actually answers `/health`, plus `/v1/health`, the root JSON response and `/health/ready`; `HEAD` added to both probes; dead `/health` route removed | ✅ `success` (CI 1m12s, image build 3m51s) |
| Forge | `0a0d9ff` | `LivenessResponse` / `ReadinessResponse` gain `evidence_class` + `observed_at`; the readiness 503 body carries them too | ✅ `success` (3m1s) |
| FRIDAY | `a745a92` | `Report.as_dict()` gains `evidence_class` + `observed_at`, stamped when the report is built, not when it is read | ✅ `success` (4m31s) |
| Futuris | `1069007` | `health_check()` gains `evidence_class` + `observed_at` | ✅ `success` (3m36s) |

Every change is **additive**: no existing field was renamed, removed, or given a
different value. `status` vocabularies differ across the nine services (`ok`, `UP`,
`healthy`, `responding`) and were deliberately left alone, because dashboards and
monitors branch on them.

### D1.5 Test results

| Repo | Command | Result |
|---|---|---|
| Cortex | `pytest tests` | **205 passed** |
| Forge | `pytest tests/unit/test_production_hardening.py tests/integration/test_api.py` | **13 passed**; `ruff check .` → *All checks passed* |
| FRIDAY | `pytest tests/test_deep_health.py` (new file, 5 tests) | **5 passed**; `ruff check` clean |
| Futuris | `pytest tests/api/test_health.py` | **3 passed** (2 new) |
| Futuris | `pytest` (full suite) | 24 failures — **proven pre-existing**: `git stash` A/B at HEAD gives the *identical* failure set (`diff` of sorted `FAILED` lines is empty). Causes are this machine only: App Control blocks the `pyarrow` DLL (`ImportError: DLL load failed`), plus `sqlite3.OperationalError: no such table` in tests that depend on init order |

**Futuris local test invocation, for the record:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
is required on this box, and pytest-asyncio must then be re-registered explicitly with
`-p pytest_asyncio.plugin`, otherwise every `async def` test silently fails to run and
the suite looks green while testing nothing.

### D1.6 Live sweep — 2026-10-02T04:52:32Z to 04:52:37Z

All nine services, `GET https://<service>.onrender.com/health`:

| Service | Live payload (verbatim) | Verdict |
|---|---|---|
| friday-zw59 | `{"overall":"healthy","evidence_class":"process_liveness","observed_at":"2026-10-02T04:52:32.955705+00:00",...,"python","details":"3.11.17"}` | ✅ **deployed `a745a92`** |
| inference-r1sn | `{"status":"responding","evidence_class":"process_liveness","evidence_scope":"...not checked.","observed_at":"...04:52:33.384285+00:00",...}` | ✅ matched before this phase |
| memora-cavc | `{"status":"healthy","service":"memora-api","database":"healthy","event_store":"turso_available","event_store_durable":true,"version":"2.0.0"}` | 🔴 **drifted** — no evidence fields |
| stratex-8wj1 | `{"dashboard":"online","engine":"online","engine_healthy":true,"evidence_class":"process_liveness","mode":"FUTURES","observed_at":"...04:52:34.570257Z","status":"ok"}` | ✅ matched before this phase |
| intelx-mygl | `{"status":"ok","evidence_class":"process_liveness","observed_at":"...04:52:35.236853+00:00","service":"INTELX","version":"2.0.0","mock_mode":false,"database":"ok","timestamp":"...04:52:35.236853+00:00"}` | ✅ **deployed `9e719ae`** |
| futuris-th6f | `{"status":"ok","version":"2.0.0"}` | 🔴 drifted **at sweep time** — CI still running; deployed 3 min later (before/after captured below) |
| cortex-0m7c | `{"status":"UP","timestamp":"...04:52:36.387704","service":"CORTEX API"}` | 🔴 **drifted** |
| forge-e9kl | `{"status":"ok","version":"2.0.0","uptime_seconds":388.1,"database_connected":true,"evidence_class":"process_liveness","observed_at":"...04:52:36.919088+00:00"}` | ✅ **deployed `0a0d9ff`** (`uptime_seconds` proves the restart) |
| sentinel-a861 | `{"status":"ok","evidence_class":"process_liveness",...,"audit_evidence_class":"audit_chain_integrity_check","observed_at":"...04:52:37.292236+00:00"}` | ✅ matched before this phase |

**Auto-deploy is on for FRIDAY, IntelX, Forge and Futuris**, and those services are
already serving this phase's code in production. That was not an assumption — it was
measured: their payloads changed shape after the pushes, and Forge's
`uptime_seconds: 388.1` timestamps the restart. Futuris is the clearest single piece of
evidence, captured before and after its own CI run finished:

```
04:54:09Z  {"status":"ok","version":"2.0.0"}                                   <- old build
04:55:46Z  CI run 36966422908 = completed success
04:55:49Z  {"status":"ok","evidence_class":"process_liveness",
           "observed_at":"2026-10-02T04:55:49.011636+00:00","version":"2.0.0"}  <- deployed
```

So: **4 of the 5 code changes are verified in live production payloads, not merely in
code and CI.**

### D1.7 Still owner-blocked: Cortex and Memora

Auto-deploy is **not** active for these two. Measured at 04:52:48Z, after pushing
`dfb37ab` and after Futuris had already auto-deployed from the same session:

```
cortex-0m7c      {"status":"UP","timestamp":"2026-10-02T04:52:50.092792","service":"CORTEX API"}
memora-cavc      {"status":"healthy","service":"memora-api","database":"healthy",...}
```

Re-checked at 04:55:49Z, after Futuris had deployed: both still unchanged.

No Render API key, deploy hook, or Render credential is reachable from this machine,
so the redeploy cannot be triggered from here. **This is an owner action, not a
failure, and it is not recorded as done.**

- **Owner action:** Render dashboard → the Cortex service → *Manual Deploy* → *Deploy
  latest commit*; repeat for the Memora service. (Setting *Auto-Deploy* on for those
  two services prevents this recurring, and costs nothing on the free plan.)
- **Verify with:**
  ```
  curl -s https://cortex-0m7c.onrender.com/health   # expect "status":"UP" AND evidence_class AND observed_at
  curl -s https://memora-cavc.onrender.com/health   # expect evidence_class AND observed_at AND database_backend AND vector_store
  ```
- **What is still owed after that redeploy:** Memora's live payload has never once
  returned `database_backend` or `vector_store`, and the Phase C journey in
  `phaseC-evidence-2026-10-01.md` was written against a **LOCAL** Memora API process
  for exactly that reason. This redeploy is the precondition for re-running that
  journey entirely in the cloud. Until it happens, the Memora row above stays 🔴.

---

## D2 — Secret scanning: 11 alerts, 0 open

The plan's premise was that the 11 alerts were real leaked keys "already rotated by
the owner." **That premise was wrong, and it is corrected here.** Every leaked blob was
fetched and read before any alert was closed. All 11 were **synthetic placeholders** in
`FRIDAY/tests/*`, all Google API Key type, all `validity: unknown` — for example
`_FAKE_GEMINI_SHAPED` (39 chars, matches the `AIzaSy` regex) and a second literal of
the form `AIzaSy…NeverStoreInDatabase12`, which is a self-describing test string rather
than a credential. **No real credential was ever exposed to
GitHub, so there was nothing to rotate** and no rotation was performed or claimed.

Note on this document: the second placeholder is written here with its middle elided
on purpose. Reproducing it in full would match the same `AIzaSy` pattern that raised
the original 11 alerts and would re-open a secret-scanning alert on this very commit.

All 11 were resolved as `false_positive`, each with an evidence comment (note: the
`resolution_comment` field caps at 280 characters).

Re-verified across all nine repositories at **2026-10-02T04:52:58Z**:

```
FRIDAY 0   Futuris 0   Memora 0   IntelX 0   Stratex 0
Inference 0   Forge 0   Sentinel 0   Cortex 0
```

`gh api "repos/surendra2304/<repo>/secret-scanning/alerts?state=open" --jq 'length'`
→ `0` for all nine. **D2 is complete.** The owner's confirmation that the keys are dead
at Google's console is no longer needed, because there was never a live key to
confirm — but the test fixtures remain deliberately fake and must stay that way.

---

## D3 — Owner session: not started, not claimed

Nine Render dashboards plus UptimeRobot, to record service IDs, deployed SHAs,
environment-variable presence, $0 billing confirmation, and monitor history. **No
Render API key, deploy hook, or UptimeRobot credential is reachable from this machine.**
Nothing in this phase is based on a dashboard I could not open. This step is recorded
as **not started**.

---

## What Phase D changed, in one line

Five services now declare, in code, in CI, and — for four of them — in live production
payloads, exactly what their health answer proves and when it observed it. In the
process two real defects were found and fixed: a Cortex health patch that would have
shipped into **unreachable dead code**, and a `HEAD` probe rejection at two Cortex
endpoints. D2 is complete with zero open alerts, and the plan's "keys already rotated"
premise is corrected: the keys were never real, so nothing needed rotating. Cortex and
Memora still serve older builds and need one Render click each; that step is **not
claimed as done**.
