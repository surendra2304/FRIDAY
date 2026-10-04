# IntelX concurrent-write deadline — measured findings

Date: 2026-10-04. Scope: the two named defects — (1) `scout` / `retriever` / `extractor`
holding SQLite's writer lock across their slow calls, and (2) `test_five_simultaneous_jobs_concurrency`
passing only ~3 of 5 runs.

Every number below was produced by running the code on this machine. Probes are listed at the end
so each figure can be re-derived.

## Headline

| | before | after |
|---|---|---|
| Per-stage writer-lock hold (worst of N, long `busy_timeout`) | scout 32.2s, retriever 32.2s, extractor 33.2s | **0.00s / 0.00s / 0.02s** |
| `test_five_simultaneous_jobs_concurrency` pass rate | 7/12 | **12/14** (see "what is still broken") |
| Live 5-concurrent submissions over HTTP | 3/5 failing, up to 56s | **15/15 HTTP 201, slowest 0.547s** |
| Live runs ending FAILED | reported 500s | **0 of 65** |
| Full IntelX suite | 203 passed, 2 skipped | 203 passed, 2 skipped |

## Defect 1 — stages holding the writer lock: CLOSED

Mechanism, per stage, adding **zero** write transactions:

- **scout** — the Task rows stay pending inside `session.no_autoflush`; the per-iteration
  `await session.flush()` is gone. The rows land at the RETRIEVING boundary.
- **retriever** — split into fetch-all-then-persist-all. `_fetch_single` is read-only and writes
  nothing; new `_persist` does the ingest.
- **extractor** — split into `_model_calls` (gateway only) and `_persist` (validation + writes).
  `execute_many` runs every model call for the batch, then every write. `execute` is now a thin
  wrapper over `execute_many`, preserving the four `tests/test_agents.py` call sites and — critically
  — keeping `execute` as the subclass seam (see "the extractor seam bug" below).

`tests/test_release_writer_lock_lifecycle.py` holds all eight stages to `max(measured) < 0.5`.
The `LOOP_STAGES` exemption for `{scout, retriever, extractor}` was deleted, not widened.

## Defect 2 — the flaky test: harness half CLOSED, production half NOT

An A/B with the production code byte-identical in both arms:

| arm | result |
|---|---|
| A: the test alone, one fresh process per repetition | 8/10 |
| B: both concurrency files in one process | 8/10 |

**The flakiness is in production, not the harness.** Arm A has no cross-test contamination and
fails at the same rate. Arm B does add a harness failure on top: plain `asyncio.gather`
re-raises the first worker failure immediately and abandons the other four mid-write, so the
autouse `clean_database_per_test` fixture then runs `DROP TABLE` underneath them
(`DROP TABLE evidence: database is locked`). `tests/test_concurrency.py` now uses
`return_exceptions=True` and re-raises per run, so no worker is abandoned and the test is
marginally *stricter*.

### Root cause of the production half

`SQLITE_BUSY`, **code 5** — a real busy-timeout expiry, not a stale-snapshot rejection.

The earlier conclusion recorded in this file was wrong and has been corrected. A previous probe
measured a *sampling* competing writer and concluded max block 0.391s, i.e. "not timeout
exhaustion". Under the real 5-way load the writer lock is held for up to **6.26s** and all five
workers block together for ~5.5s.

The earlier per-stage probe also measured the wrong thing. It timed first-write → last-write, which
reported 0.00s, and so missed the holder entirely. Timing first-write → **commit** shows a
transaction spanning **5.9s across 4 statements**, with the gap between consecutive writes up to
**5.92s**:

```
+0.000s  UPDATE research_runs SET plan_json=?
+5.716s  UPDATE research_runs SET status=?, outcome=?, error_json=?, completed_   <- 5.7s blocked
+6.261s  INSERT INTO events
```

and, attributed to the stage that filled it:

```
after:planner -> after:emit_event   n=1  total 5.92s  max 5.92s
```

Writes *within* a transaction are 1–20ms apart; 55 of them complete in 0.3s. The time is not spent
writing — it is spent holding the transaction open across a stage.

**Cause:** `transition_state` flushed its status write but never committed, so a write transaction
opened at one stage boundary was not closed until the *next* stage's `release_writer_lock`, i.e.
it spanned a stage. `transition_state` now commits its own writes, and the planner commits its
`plan_json` write. **No write transactions were added** — the same statements are issued, the
transaction just ends where the write is made.

## Why it is still ~1 failure in 7

`BEGIN IMMEDIATE` on every transaction removes the failure completely, and was measured
interleaved on the same machine:

| arm | pass rate | median wall |
|---|---|---|
| deferred BEGIN (production) | 3/8 | 6.55s |
| BEGIN IMMEDIATE | **8/8** | **2.03s** |

with zero busy errors, and 32/32 on the full concurrency loop.

It was **reverted** because it is a real regression, not a test artifact: it makes read-only
transactions take the writer lock too, so `release_writer_lock`'s `refresh` *acquires* the lock
instead of releasing it. That left a second writer blocked **3.23s** during synthesis and failed
13 tests including every `test_stage_does_not_hold_the_writer_lock`.

Scoping it to write phases only was tried at three levels — all three write sites, plus the
pre-write commits that flush pending rows, plus a context-var `write_transaction()` — and landed at
**7/14, 9/14, 9/14**. Partial application does not work, because a transaction opened outside the
block is still a deferred read-then-write.

Also measured and rejected: raising `busy_timeout` 5000 → 60000 ms took pass rate 3/8 → **1/8**
and turned each 6s failure into a **66s** failure. The timeout is not the lever.

### What closing it actually requires

The two requirements are in tension only because read work sits inside a transaction:

1. no transaction may upgrade a read snapshot into a write (needs IMMEDIATE), and
2. no read-only transaction may be held across slow I/O (needs readers outside a transaction).

`BEGIN IMMEDIATE` satisfies (1) globally and breaks (2). Scoping satisfies both but misses
transactions opened on other paths. **The complete fix is to run a stage's read-only work on a
separate autocommit connection**, so the engine's session only ever opens write transactions.
That is an architectural change to how agents receive their session, and was not attempted here.

## The extractor seam bug (found and fixed, not a behaviour regression)

`execute_many` originally bypassed `ExtractorAgent.execute`. Four test doubles override `execute`
(`test_orchestration.py` ×2, `test_prompt6_intelx.py`, `test_artifacts.py`), so the stubs were
skipped, real ACTIVE claims were created, and two runs reported `ANSWERED` instead of
`CONTRADICTION_DETECTED` / `INSUFFICIENT_EVIDENCE`. Confirmed by bisection: reverting only
`extractor.py` to HEAD made both pass.

`execute_many` now hands its pre-computed extractions back through `self.execute(...)`, so
overriding `execute` still substitutes the agent's behaviour while all model calls still precede
all writes. **No test was weakened or changed to accommodate this.**

## Still broken, with numbers

1. **`test_five_simultaneous_jobs_concurrency` is 12/14, not deterministic.** Root cause and the
   complete fix are above. Not hidden with xfail, timeout or retry.
2. **The Friday research endpoint has a hard 50 req/hour per key** (`intelx/core/auth.py:138`).
   Exhausting it returns HTTP 429 and blocks further live probing. This is why terminal run state
   was verified from the live database rather than over HTTP.
3. **Submissions are accepted far faster than the pipeline drains them.** 65 submissions produced
   a backlog of 21–23 QUEUED runs; `MAX_CONCURRENT_RUNS = 5` and runs take 92s (`NO_EVIDENCE_FOUND`)
   to 178s (`ANSWERED`). The queue does drain — COMPLETED went 69 → 71 and QUEUED 23 → 21 over
   150s — but a client that receives 201 has no signal about the wait ahead of it.
4. **Pre-existing, unrelated:** `nvidia/nemotron-3-super-120b-a12b` returns HTTP 410 Gone;
   openrouter 401; groq key unrecoverable; `SENTINEL_STORAGE_BACKEND` unset on Render; Memora
   `sqlalchemy-libsql` has no Windows wheel.
5. **Ruff** reports 3 pre-existing errors in files this work does not touch
   (`intelx/core/auth.py:3` I001, `intelx/integrations/ecosystem_dispatch.py:3` I001 and `:60` UP041).
   Verified identical at HEAD.

## Reproducing

```
cd "D:\FRIDAY Universe/IntelX"
python scripts/conc_loop.py 14                 # determinism over the two concurrency files
python scripts/diag_gap_owner.py               # intra-transaction gaps, attributed to a stage
python scripts/live_concurrent_verify.py 5 2   # live 5-concurrent submissions + terminal states
python -m pytest tests/ -q                     # 203 passed, 2 skipped
```

Per-stage lock hold uses the long-`busy_timeout` probe so block time is the measurement, never the
probe's own give-up time.