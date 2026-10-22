# IntelX read-connection split — attempted, measured, ruled out

**Date:** 2026-10-05
**Repo:** IntelX, parent commit `bcecb13`
**Verdict:** **Not shipped.** The shape was built, both invariants held where it was applied, and the measurement ruled it out.
**Shipped instead:** `b58ac60` — the `scripts/conc_loop.py` instrument fix only.

> ## ⚠ The test suite is still red at `bcecb13`. "Untouched" is not "green."
>
> Reverting the split restored the tree to `bcecb13`, and that tree **fails
> `tests/test_concurrency.py::test_five_simultaneous_jobs_concurrency_and_state_isolation`
> on a minority of runs** — 2 of 6 full-suite runs measured on the clean tree after
> the revert, 13 of 30 lock-guard iterations at `b58ac60`. The committed stranded-run
> fix (`bcecb13`) made those failures *recorded* rather than *stranded*; it did not
> stop them. Nothing in this pass made the suite greener, and no one should read
> §6 ("zero tracked modifications") as an all-clear.

---

## 1. What was asked

Make the pipeline's session only ever open write transactions, by moving stage reads onto a separate read connection, so a read can never hold a snapshot that blocks the next write.

Constraints: reads that must see writes preceding them in the same run must still see them; no per-run state bleeding between concurrent workers; `busy_timeout` stays 5000; no xfail/skip; no existing test modified or weakened; prove with `scripts/conc_loop.py` at n≥30 and report the exact pass count; state the full-suite flake rate before and after.

## 2. What was built, and then reverted

A throwaway read session that opens one statement and closes it, so its snapshot cannot outlive the statement:

```python
async def committed_row_text(model, row_id, column_name):
    async with get_sessionmaker()() as read_session:
        row = await read_session.get(model, row_id)
        return None if row is None else getattr(row, column_name)
```

Applied at the two identified poisoning reads — the `SourceRepo.get_document` SELECTs inside `ClaimRepo.create_claim` and `EvidenceRepo.create_evidence` (**`repos.py:524` and `:653` on the reverted tree**), each of which read immediately before an INSERT.

`None` is load-bearing: it means "this row is only a pending write on your own session," so the caller reads it from its own session. That is what preserves read-your-writes.

### The boundary, stated precisely

A read is safe to move **only where it follows a committed write**. That holds for both sites: `transition_state(EXTRACTING)` commits the retriever's writes before any claim is created, so the `Document` row is durable by then. `tests/test_repos.py:118-149` exercises the opposite case — a document created in the same uncommitted session — which is exactly what the `None` fallback exists for. Measured: `tests/test_repos.py tests/test_trust.py tests/test_release_writer_lock_lifecycle.py` → **25 passed**, both before and after the maintainer's cut below.

Per-run state: the read session opens, runs one statement and closes inside a single call, holds nothing beyond it, and binds to the same engine pool (`AsyncAdaptedQueuePool`, 5 + 10 overflow) — 5 write sessions + 5 throwaway reads fits. No global, no per-run bleed.

`busy_timeout` untouched at 5000. No test modified, weakened, skipped or xfailed.

### Four rewrites before it ran

Each was an API error of mine, not a product defect. Recorded because the final form is not where it started:

1. `isolation_level="AUTOCOMMIT"` on `async_sessionmaker(...)` → `TypeError: Session.__init__() got an unexpected keyword argument 'isolation_level'`
2. `async with get_sessionmaker()` → `TypeError: 'async_sessionmaker' object does not support the asynchronous context manager protocol`
3. `read_session.execution_options(...)` → `AttributeError: 'AsyncSession' object has no attribute 'execution_options'`; `.sync_session.execution_options(...)` → `AttributeError: 'Session' object has no attribute 'execution_options'`
4. `getattr(row, column)` with an `InstrumentedAttribute` → `TypeError: attribute name must be string, not 'InstrumentedAttribute'`; passing `"text"` to `load_only` → `ArgumentError: expected ORM mapped attribute for loader strategy argument`

### The maintainer's cut

`load_only(column)` + `column.key` gymnastics were cut, along with a separate `get_read_sessionmaker()` that differed from `get_sessionmaker()` in no behaviour. `load_only` was loading one column of a row whose only used column is that one. Final form: four lines. **It changed no result — 25 passed before and after.**

## 3. The measurement that ruled it out

| | conc_loop n=30 | full suite, 6 runs |
|---|---|---|
| Baseline (`bcecb13`) | **17/30** | **2/6** (the figure on the record before this pass was 3/6) |
| With the split | **18/30** (10/15 + 8/15) | **3/6** |

18/30 against 17/30 is a one-iteration difference and both full-suite numbers are a single run apart. Every difference here is inside noise. **The flake did not improve.**

### The failure mode — as the raw records actually show it

All 30 iterations ran the same 17 tests across three files. **12 failed, and all 12 were the same test**, `test_five_simultaneous_jobs_concurrency_and_state_isolation`. They did **not** all present the same way:

- **10 of 12** failed as `AssertionError: assert <RunStatus.FAILED: 'FAILED'> in (<RunStatus.COMPLETED>, <RunStatus.REVIEW_REQUIRED>)` — the run reached a terminal FAILED with the cause recorded. This is the `bcecb13` behaviour working as designed.
- **2 of 12** (`run 6` of the first 15, `run 3` of the second) failed as `PendingRollbackError` **escaping `execute_run`**, which the test converts into `AssertionError: run <id> raised PendingRollbackError: ... Original exception was: (sqlite3.OperationalError) database is locked`.

Underneath every one of the 12, the recorded cause is `(sqlite3.OperationalError) database is locked` on the **write path of the pipeline's own session**. The statements that lost the race were not only the three the first draft listed — the full set across the 12 records is:

- `UPDATE research_runs SET status=? WHERE research_runs.id = ?` (`'PLANNING'`, `'RETRIEVING'`)
- `UPDATE research_runs SET plan_json=? WHERE research_runs.id = ?`
- `UPDATE research_runs SET input_tokens=?`
- `INSERT INTO claims`, `INSERT INTO sources`, `INSERT INTO tasks`, `INSERT INTO events`

**Not one of the 12 failures came from either read that was moved** — no SELECT appears in any failure record. Moving those two sites removed two poisoning snapshots out of many and left the mechanism untouched.

### Two corrections this pass makes to the earlier record

1. **The earlier "zero `PendingRollbackError`" claim does not survive n=30.** The stranded-run report recorded that no `PendingRollbackError` appeared across its 6 post-fix full-suite runs. That was true of those 6 runs. At n=30, **2 of 12 lock-guard failures still escaped `execute_run` as `PendingRollbackError`.** So `bcecb13` narrowed the stranded-run window; it did not close it. The precise mechanism behind those 2 escapes is **not established here** — the captured records show the terminal-write SQL and the recorded error, but not which statement re-deactivated the session after the handler's rollback-and-retry. That is an open question, not a solved one.

2. **Baseline concurrency is 17/30, not 22/30 — and not 23/30 either.** Both stale figures were produced by the old four-test loop. See §5.

## 4. Why a complete migration cannot satisfy both invariants

`_check_gates` (**`engine.py:204`**) opens with `run = await RunRepo.get_run(session, run_id)` — a SELECT on the pipeline's session — and then, in the same call, mutates that same identity-mapped object (`run.input_tokens = ...; await session.flush()`) and writes (`RunRepo.set_status`, `emit_event`). It is **read-then-write on one session by construction**, and it runs between every pair of stages. It cannot move to a read connection without breaking read-your-writes, because the object it mutates is the caller's live object.

That adjacency is exactly what produces `database is locked`: a read opens a deferred transaction, another worker commits inside it, and the next write cannot upgrade the stale snapshot.

The read→write adjacency is intrinsic to how the pipeline is written, so eliminating it site by site is not a completable migration. There are ~210 `session.commit/flush/execute` call sites; it cannot be verified at session-creation time, because `session.new` and `session.dirty` are both empty after a Core write; and every site missed silently restores the flake.

So the conclusion is **not** "the split was too small." It is: the split cannot hold both invariants at once, because invariant (a) requires some reads to stay on the write session — and it is precisely those reads, sitting in front of a write, that cause the lock failure.

## 5. Instrument correction (the only thing shipped)

`scripts/conc_loop.py` had two flaws that made every number above under-report what was claimed:

1. It ran only `test_concurrency.py` and `test_concurrent_runs.py` — **4 tests** — while the lock guards are **17 across three files**. `test_release_writer_lock_lifecycle.py`, covering the writer-lock boundary this work is about, was never executed.
2. It passed no `-m "not live"`, so a live-marked test would make the tally depend on provider keys rather than on the code, and it inherited whatever environment the caller exported. It now pins `INTELX_ENV=testing`, `INTELX_MOCK_MODE=true`, `INTELX_DB_URL` at `<repo>/data/test_intelx.db`, and `PYTHONHASHSEED=0`.

### Correction on the record — read every earlier concurrency figure against these numbers

| Figure | Where it appears | What it actually measured |
|---|---|---|
| **23/30** | `intelx-write-transaction-split-2026-10-04.md` (lines 8, 14, 96, 142) | 4 tests, not 17 |
| **22/30** | `intelx-failed-run-terminal-state-2026-10-04.md` (lines 94, 118) | 4 tests, not 17 |
| **17/30** | this report | all 17 lock guards |

Both prior figures were honestly measured — on a smaller instrument. Any comparison drawn between them and a 17-test tally, in either direction, is invalid. The corrected instrument is the only one that covers `test_release_writer_lock_lifecycle.py`, and on it the committed baseline is **17/30**. (`tests/conftest.py:14-17` does force the same env at import, so the old loop's environment was in practice fine — the test-count flaw is the substantive one.)

## 6. State left behind

- `intelx/db/session.py` and `intelx/db/repos.py`: **reverted, byte-identical to `bcecb13`** (`git diff bcecb13 HEAD` on both paths is empty).
- Zero tracked modifications in IntelX. **`b58ac60` contains only the instrument fix.** Nothing from the split was committed. Nothing pushed.
- Untracked probe scripts from the ruled-out approaches remain untracked and uncommitted.
- **The suite is still red** — see the banner at the top. Clean tree, failing test.

## 7. Where this leaves the real defect

The split targeted the right cause and failed because the cause is spread through the design. Two things would actually move it, neither being a read/write split:

- **`get_or_claim_next_queued_job` (`repos.py:83`) counts statuses with no lease or heartbeat.** A worker lost mid-run strands one of the five `MAX_CONCURRENT_RUNS` slots (`core/settings.py:288`) permanently, so concurrency silently degrades over a long-lived process. This is orphan-liveness, not locking — smaller and far more provable.
- **Serialising writers explicitly** — one connection taking the write lock for a stage with others waiting on it. The raw-`sqlite3` probe showed 5 read-then-write workers: deferred `BEGIN` → 1/5 succeed, `BEGIN IMMEDIATE` → 5/5.

Open question left by this pass: **why do 2 of 30 lock-guard failures still escape `execute_run` as `PendingRollbackError`** after `bcecb13`'s conditional rollback? That is the highest-value loose end here.

Note for whoever picks this up: `orchestration/engine.py:195` references `db.engine.write_transaction` — **no such function exists**. The comment is stale and will mislead.