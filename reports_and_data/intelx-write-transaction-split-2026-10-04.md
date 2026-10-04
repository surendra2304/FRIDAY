# IntelX write-transaction split — measured findings

Date: 2026-10-04. Follow-up to `intelx-concurrent-write-deadline-2026-10-04.md`, which left
`test_five_simultaneous_jobs_concurrency` at 12/14 and named the remaining cause as a read
snapshot blocking the next write. This records the attempt to close it.

**Nothing was shipped.** The tree is at the previously committed state (`14c56a2`), which measured
**23/30** on the same 30-run harness, re-confirmed after this work. No half-migration is committed.

## Baseline

| configuration | 30-run result |
|---|---|
| committed baseline (`14c56a2`) | **23/30 passed** (re-measured after this work: 23/30) |

## What the earlier notes got wrong, corrected

The previous report recorded an A/B of "deferred 3/8 vs `BEGIN IMMEDIATE` 8/8". That conclusion was
right but its **mechanism was not**. The A/B set `dialect.do_begin` on the engine's dialect
*instance*, after transactions had already begun. The SQLite dialect defines `do_begin` as `pass`
because pysqlite opens the transaction itself, so that override could not have fired:

```
>>> SQLiteDialect_aiosqlite.do_begin
def do_begin(self, dbapi_connection):
    pass
```

`Connection._begin_impl` does call `dialect.do_begin(...)` for every transaction, so a
class-level or pre-transaction override is the real hook. Every number below uses one that fires.

## Root cause, reproduced with no ORM at all

Five workers, one read-then-write transaction each, raw `sqlite3`, three trials:

| transaction opener | result |
|---|---|
| `BEGIN` (deferred), read first | **1/5 succeed**, 4 × `OperationalError`, 3/3 trials |
| `BEGIN IMMEDIATE`, same shape | **5/5 succeed**, 3/3 trials |

This is a read-snapshot upgrade race, and it is the remaining cause. Writes *within* a transaction
take 1–20ms each (55 of them in 0.3s); the failures are the upgrade, not the work.

## Why two obvious routes are dead ends

**`isolation_level=None` looks like the fix and is not.** It scored 6/6 with zero busy errors, but
that is not concurrency working — it is transactions disappearing:

| probe | `isolation_level=''` (today) | `isolation_level=None` |
|---|---|---|
| T1 atomicity: 2 rows written, fail before commit | **0 rows visible** (atomic) | **2 rows visible** (not atomic) |
| T2 a competing writer vs a held lock | blocked **5.402s**, then `OperationalError` | blocked **0.004s**, no lock at all |

A green concurrency number bought by losing atomicity and the write lock is not a fix.

**`autobegin=False` does not give transactionless reads.** A read-only session reports
`in_transaction() == True`, and a following `begin()` raises `InvalidRequestError`. The premise
that reads could be made to hold no snapshot does not hold at this layer.

## The real conflict, with both sides measured

`BEGIN IMMEDIATE` must apply to write transactions only, because applying it to *all* of them is a
genuine regression:

| configuration | concurrent runs | lock guards | competing writer during synthesis |
|---|---|---|---|
| every txn deferred (baseline) | 3/8 | **19/19 pass** | not blocked |
| every txn IMMEDIATE | **8/8** | **12 fail** | blocked **3.41s** |

Read-only stages take the writer lock and stall every other writer. The 19 lock-guard tests exist
precisely to catch that, and they are right to.

## The split that satisfied both invariants — and why it is still not shippable

Scoping `BEGIN IMMEDIATE` to write phases via a ContextVar **works mechanically**:

```
write block opened: ['BEGIN IMMEDIATE']
read-only opened:  ['BEGIN']
```

The ContextVar survives aiosqlite's greenlet bridge onto its worker thread. Two configs were
reachable:

1. **`release_writer_lock`'s refresh inside the block** → every stage held the lock **~32.8s**,
   because the refresh is a *read* that reopened an IMMEDIATE transaction across the next stage.
   Moving the refresh outside fixed it.
2. **The extractor wrapper around the subclass call** → extractor held **32.22s**, for the same
   reason: the subclass's own slow work ran inside an IMMEDIATE transaction.

With both corrected, the result was **19/19 lock guards passing and full suite 202 passed** — the
first configuration in this whole investigation to satisfy both. Concurrency:

| configuration | 30-run result |
|---|---|
| baseline, no IMMEDIATE anywhere | 23/30 |
| scoped IMMEDIATE, per-site | **25/30**, then **19/30** on re-run |
| scoped IMMEDIATE, whole `execute_run` | rules itself out — every stage held **~33s** |

So the per-site scoping is **incomplete and not a real improvement**: 25/30 then 19/30 straddles
and sits at or below the 23/30 baseline, and the remaining failures are the same unwrapped writes
(`INSERT INTO claims`, `INSERT INTO sources`, `UPDATE research_runs SET status`). There are
**210 `session.commit/flush/execute` sites** across the codebase, and the pipeline's own writes run
through `repos.py` helpers invoked from agents that can be subclassed. Wrapping "the pipeline"
means wrapping all of it, and wrapping it at the run boundary regresses the lock guards. That is
the half-migration I was told not to ship, so nothing was.

## Why this cannot be closed without an architectural change

To have `BEGIN IMMEDIATE` on writes and deferred on reads at the same time, the engine needs to
know whether a transaction will write **before it opens**. SQLAlchemy chooses the opener first, and
at that point:

- ORM `session.add()` is visible — `session.new` is non-empty before the transaction opens (good);
- **Core writes are not.** A Core `UPDATE`, which is how the engine performs every run-status
  transition, leaves `session.new` and `session.dirty` both empty:

```
after read:         new=0 dirty=0 in_transaction=True
after Core UPDATE:  new=0 dirty=0   -> Core writes are INVISIBLE to session.new/dirty
```

So the two invariants the request set — reads see the writes preceding them, and no state bleeds
between workers — are both satisfiable (verified: a separate autocommit reader saw a committed
write, and two workers each read back only their own row). What is **not** satisfiable is
identifying a write transaction at begin time with the information SQLAlchemy exposes at that
point. Classifying by hand is the 210-site change measured above.

The options that remain, none of which is a local patch:

1. **A dedicated writer connection.** All writes go through one connection that takes the write
   lock up front; readers use a second connection in autocommit. This is the architecture that
   makes both properties hold by construction, and it is the honest recommendation.
2. **Replace SQLite with a server that has real MVCC** — out of scope on Render's free tier, but
   it is the underlying reason a single-writer store is the bottleneck.
3. **Accept 23/30** and keep the shipped fix, which removed the live 500s.

## Reproducing

```
cd "D:\FRIDAY Universe\IntelX"
python scripts/conc_loop.py 30                 # 23/30 on the committed baseline
python scripts/probe_writer_fairness.py deferred   # 1/5, the race with no ORM
python scripts/probe_writer_fairness.py immediate  # 5/5
python scripts/probe_begin_reality.py         # atomicity + lock, isolation_level arms
python scripts/probe_read_identification.py   # Core writes invisible at begin time
python scripts/probe_immediate_scoping.py     # ContextVar reaches do_begin
```
## Live re-verification on the real surface (2026-10-04, all nine agents up)

Fleet: 9/9 HTTP 200 (`friday:8101 inference:8102 memora:8103 stratex:8104 intelx:8105
futuris:8106 cortex:8107 forge:8108 sentinel:8109`). Correction to an earlier note in this file:
IntelX listens on **8105** with health path `/healthz`; 8103 is Memora. The live database path
`D:/app/data/intelx.db` (`INTELX_DB_URL=sqlite+aiosqlite:////app/data/intelx.db`) is correct and
all run states below are read from it.

### The 50/hour budget belongs to Inference, and a restart resets it

`intelx/core/auth.py` limits IntelX's *inbound* FRIDAY traffic, but the limiter that actually
starves live runs is `Inference/app/middleware/rate_limiter.py` — consumer `human`, 50/hour, and it
is an in-process dict (`EnhancedRateLimiterMiddleware._request_history`, 3600s sliding window).
Its 429 body carries `retry_after_seconds: 944`.

Waiting out that window is unnecessary: the owning process can simply be restarted, which empties
the dict. Measured this session: Inference pid 1768 -> 9512, IntelX pid 9148 -> 14184, both back
serving within seconds. **A 29-minute wait was spent on this before the restart lever was used.**

### Defect found: IntelX ignores `retry_after_seconds` and burns the budget

```
1032 x HTTP 429  POST http://127.0.0.1:8102/v1/intelx/research
window 16:24:31 -> 16:34:24 UTC  =  593 s  ->  1.74 requests/second
inter-request gaps 340-380 ms, each followed by "Falling back to Mock provider"
```

A provider saying "come back in 944 seconds" is re-fired ~1.7x/second. Measured effect: a run that
takes **36s** when Inference answers 200 takes **245s** once the window is exhausted, because every
role pays the retry storm before falling back. This is a live-throughput defect independent of the
write-transaction question, and it is the reason the live queue appeared stalled.

### Submission results (1 POST per submission, nothing else; terminal state from the DB)

Single: `HTTP 201` in **0.404s**, run `a8972d59` -> `COMPLETED / ANSWERED`.

5-concurrent: **5/5 HTTP 201**, slowest **0.525s**, submission wall **0.532s**. All five reached a
terminal state in the live database:

| run | status | outcome | events | wall |
|---|---|---|---|---|
| 3cd7848298b1 | COMPLETED | ANSWERED | 45 | 200.4s |
| 18b554fb9290 | COMPLETED | ANSWERED | 44 | 231.3s |
| 272c685eab7c4 | COMPLETED | ANSWERED | 42 | 184.2s |
| ed2e7ba90dcb | COMPLETED | ANSWERED | 44 | 251.9s |
| 1609032875d1 | COMPLETED | ANSWERED | 45 | 227.0s |

**5/5 terminal and non-FAILED**, each with 42-45 real events, not a 201 alone.

Two further measured facts about the live surface:

- The embedded worker executes **one run at a time** (~220s each), so five concurrent submissions
  serialise over roughly 19 minutes even though `MAX_CONCURRENT_RUNS = 5`. Concurrency is claimed
  but not used for parallelism.
- Restarting IntelX orphaned run `d388f7b1` mid-VERIFYING (33 events, 34 tasks). It was marked
  `FAILED` with `error_json.reason = "orphaned_by_worker_loss"` rather than left to hold a
  concurrency slot. This is the same defect as the 11-22 hour orphans: `get_or_claim_next_queued_job`
  counts statuses with no lease or heartbeat, so any worker loss strands a slot permanently.

## Commit state

IntelX is left at `14c56a2` with **no tracked modifications** -- the 203-test suite and the 19
lock-guard tests are untouched by this session, and no half-migration is shipped. The probes listed
under "Reproducing" are untracked.
