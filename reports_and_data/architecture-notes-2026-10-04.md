# Architecture notes — 2026-10-04

Shape of the code touched by the IntelX writer-lock and Futuris refresh-budget
work. Behavior is unchanged; this records where each concern now lives so later
passes extend it instead of re-deciding.

## Futuris — forecast generation is core, not interface

```
futuris/core/universe_domains.py      target specs, UNIVERSE_TARGETS, risk levels
futuris/core/universe_forecasting.py  how a forecast is derived; refresh pacing
futuris/api/routers/predictions.py    request/response models; three routes
```

`core/universe_forecasting.py` owns:

| Symbol | Role |
|---|---|
| `REFRESH_BUDGET_SECONDS` | the single definition of how long a refresh may take |
| `generate_universe_forecast()` | derive one target's forecast (was `_generate_universe_forecast`) |
| `_paced_pass()` | the one budget accounting: walk targets, stop when the budget is spent |
| `refresh_all_within_budget()` | refresh every target |
| `refresh_missing_within_budget()` | backfill only targets with no active forecast |

The router is now interface only: five Pydantic models and three handlers, 284
lines. It reads active forecasts through `ForecastRepository` and assembles the
response model — that is presentation, so it stayed.

Before: `predictions.py` was 527 lines holding 200 lines of domain computation,
two copies of the budget loop, and the budget constant. `demo/seed.py` imported
`_generate_universe_forecast` **from the API router** to seed data — a demo
reaching into presentation for domain logic. That import now points at core.

### State ownership

`REFRESH_BUDGET_SECONDS` has exactly one definition, and it sits next to the loop
it paces. Previously each loop restated the arithmetic inline, which is how the
two drifted apart.

## IntelX — transaction mechanics belong to the session

```
intelx/db/engine.py       connection, pragmas (busy_timeout), pool
intelx/db/session.py      session lifecycle + release_writer_lock()
intelx/orchestration/engine.py   decides *when* a stage boundary is
```

`db.session.release_writer_lock(session, run)` owns *how* a write transaction
ends: `commit()` then `refresh(run)`, returning a usable `run`. The orchestrator
states the policy — no write transaction may span a stage that calls out — and
calls the helper at each boundary.

Before: two verbatim copies of `await session.commit()` / `await
session.refresh(run)` with near-identical four-line comments restating the same
rule at both call sites.

## Open, not addressed here

**IntelX research submissions still fail under load.** The mesh probe is 18/19;
`intelx trigger research` returns HTTP 500 after ~23.7–24.5s, consistently across
three runs. Cause is unchanged and measured earlier: SQLite permits one writer,
and `execute_run` writes throughout a multi-minute pipeline, so submissions
contend with the worker. The retry budget (4 attempts x 5s busy_timeout + 1.4s
backoff, ~21.4s) is smaller than the observed hold (29.14s).

Attempts to add transaction boundaries at every stage did not fix it: the live
number got worse (38.9s -> 44.6s) and `test_five_simultaneous_jobs_concurrency`
started failing, because more write transactions means more contention. Those
changes were reverted. This needs the state moved to Turso/Postgres or run
execution serialized — not another commit site.
