# IntelX: a failed run now reaches FAILED instead of being stranded

Date: 2026-10-04. IntelX `14c56a2` + this pass. Report lives in FRIDAY; the code is in IntelX.

## The defect

`OrchestrationEngine.execute_run` caught a stage failure and then wrote the terminal state on
the *same* session:

```python
except Exception as e:
    run.status = RunStatus.FAILED
    ...
    await session.flush()          # <-- raises PendingRollbackError
```

When the failure came out of the database itself, SQLAlchemy had already deactivated that
transaction. The handler's own write therefore raised `PendingRollbackError` *from inside the
error handler*, `execute_run` propagated, the caller never reached its commit, and the run was
left in whatever stage it died in -- `QUEUED` in the reproduction. Nothing claims a non-terminal
run, so it is an orphan holding a concurrency slot forever.

## Diagnosis: two different root causes, only one fixed here

The audit reported two measured failures at this site. They are causally linked but have
different roots, and they are fixed separately.

**Fixed here -- the error path.** Once *any* database error kills the run's transaction, the
handler cannot record the terminal state. That is a pure control-flow defect with no locking
involved.

**Not fixed here -- lock contention.** `(sqlite3.OperationalError) database is locked` from
`INSERT INTO claims` is the read-snapshot upgrade race already characterised in
[intelx-write-transaction-split-2026-10-04.md](intelx-write-transaction-split-2026-10-04.md):
a deferred `BEGIN` reads a snapshot, and the later write cannot upgrade while another writer
holds the lock. Measured with raw `sqlite3`, 3/3 trials: deferred `BEGIN` 1/5 succeed,
`BEGIN IMMEDIATE` 5/5. It is not fixable as a local patch, so it is deliberately left alone
rather than folded into this change.

The distinction is observable in the test suite: before this pass the contention surfaced as
`AssertionError: run <id> raised PendingRollbackError`; after it surfaces as
`assert <RunStatus.FAILED> in (<RunStatus.COMPLETED>, <RunStatus.REVIEW_REQUIRED>)`. Same
contention, different consequence -- a cleanly recorded `FAILED` instead of an orphan.

## The fix

One helper, `_settle_terminal_state`, used by all three error branches
(cancelled / budget exceeded / unhandled):

1. Attempt the terminal write first. A stage can also fail while its session is perfectly
   healthy -- the budget ceiling raises before anything is wrong -- and that transaction may
   already hold writes worth keeping.
2. Only if the session refuses (`PendingRollbackError`) roll back and write again. Rolling back
   *unconditionally* was the first attempt at this fix and it broke
   `test_orchestration_budget_ceiling_gate`, because it discarded the uncommitted
   `budget.exceeded` event the gate had just written.
3. Commit inside the handler. The terminal state must not depend on the caller reaching its own
   commit; the worker, the API and the tests each commit differently, and one of them did not
   commit at all on this path.

A failure to persist the terminal state is logged, never raised -- raising there is what caused
the strand.

Two incidental corrections in the same branches: the budget branch now records
`error_json`, and the cancellation event is emitted with the *previous* status as its `from`
value rather than the already-updated one.

## Proof

**Reproduction, before the fix** (`scripts/probe_failed_run_terminal.py`, two scenarios):

| scenario | before | after |
|---|---|---|
| stage raises `RuntimeError` | FAILED, reason recorded | FAILED, reason recorded |
| DB error during flush | **`PendingRollbackError`, stranded in `QUEUED`** | FAILED, reason recorded |

The injection has to fail *during flush*; an error from a bare `session.execute()` does not
deactivate the transaction and will not reproduce it. The first version of this probe got that
wrong and appeared to pass.

**Regression test** `tests/test_orchestration.py::test_failed_run_reaches_failed_state_when_session_is_poisoned`
passes on the fix and fails on the pre-fix file with exactly `PendingRollbackError`.

**Flake rate, full suite, same machine, six runs each:**

| | failures | which test |
|---|---|---|
| before | 3/6 | `test_five_simultaneous_jobs_concurrency_and_state_isolation` |
| after | 3/6 | same test |

The rate is unchanged, as expected: that test asserts all five runs *complete*, so a correctly
recorded `FAILED` still fails it. What changed is the mechanism -- zero `PendingRollbackError`
across all six post-fix runs, and the failing assertion is now about completion, not about a
broken error path. `conc_loop.py 30` measured 22/30 before this pass.

**Live surface.** IntelX restarted onto the new code, one submission: HTTP 201, run
`4401268c422f` -> `COMPLETED / ANSWERED`. A successful run is unaffected.

Constraints held: `busy_timeout` untouched (still 5000 in `db/engine.py`), no `xfail`, no
`skip`, no existing test modified -- the only test change is one added. Ruff clean.

One honest cost: restarting IntelX to load the fix orphaned live run `e4688ab636ec`, which was
marked `FAILED` / `orphaned_by_worker_loss`. Process death still strands runs; that is the
missing lease in `get_or_claim_next_queued_job`, and this pass does not address it.

## Also found, not fixed

`intelx/orchestration/engine.py:193` documents the transaction rule as "See
`db.engine.write_transaction`". **No such function exists** in `intelx/db/engine.py`. The
comment points at an API that was never written, and it is the one place a maintainer would look
to understand the write-transaction rule.

## Reproducing

```
cd "D:\FRIDAY Universe\IntelX"
python scripts/probe_failed_run_terminal.py                  # 2/2, exit 0
python scripts/conc_loop.py 30                               # 22/30
```