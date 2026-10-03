# Phase B — learn-from-mistakes, measured

**Date:** 2026-10-03 · **Owner:** Surendra · **Verdict: the recall path is REAL and works.**
Reproduce with `python research/phaseB_recall_proof.py` (exit code 0).

The phase was labelled COMPLETE and this file did not exist. The code was genuinely
wired — `agent.py:302` calls `build_self_upgrade_context(...)` and injects the
result behind a quarantine header — but "the code is wired up" is not the same
claim as "a lesson survives the round trip", and only the first had been made.

So this measures the second one. Nothing below is mocked below the public API and
the database is a real file on disk.

## What was exercised

A real failure was recorded, a real lesson was synthesized from it, and a real
recall was asked for it back — then the database was closed and reopened and the
lesson asked for a second time.

| step | result |
|---|---|
| `learn_from_outcome(...)` on a real failure | `status: local_only`, `cloud: False` |
| lesson present in `memory_records` | 1 row, `memory_type: experience` |
| `recall_experience(...)` returns it | 1 experience, matching text |
| `build_self_upgrade_context(...)` | block built, quarantine header present |
| after reopening the database | block still built, 576 chars — durable |

## Two findings this surfaced

Both were found by running the path, not by reading it.

### 1. An explicit `local_db_path` is silently discarded if the file does not exist yet

`MemoraClient.__init__` resolves the database through a candidate list and only
accepts a path that **already exists**:

```python
self.local_db_path = next(
    (p for p in candidates if p and (p == ":memory:" or os.path.exists(p))),
    default_local,
)
```

So a passed-in `local_db_path`, or a `MEMORA_DB_PATH` pointing at a not-yet-created
file, is dropped without a word, and the client falls through to a relative
`data/memora.db` or to a hardcoded `d:/FRIDAY Universe/Memora/data/memora.db`.

Why this matters on the deployed service: relative `data/memora.db` is ephemeral
per deploy on Render, so learned lessons do not survive a redeploy. The hardcoded
absolute path means a machine that does not have that layout silently writes
somewhere else entirely.

**Not changed here.** It changes which database the product writes to, which is a
deployment-visible decision. It is recorded in the Phase F3 checklist as an owner
item instead.

### 2. `recall_experience` accepts `agent_name` and never uses it

`_recall_experience_locally` has no agent filter in its `WHERE` clause. It joins
`agents` only to read `a.name`, and returns it as `owner_name` — the name is
reported, never filtered on. Every agent therefore receives every agent's lessons,
ranked by keyword overlap.

This may well be intended: a fleet sharing operational lessons is a reasonable
design, and `source` does record who learned each one. But the parameter name
promises something narrower than the behaviour delivers. **Recorded, not changed** —
it is a product decision about whether lessons are per-agent or fleet-wide.

## Verbatim transcript

```
  real database : C:\Users\Surendra\AppData\Local\Temp\phaseB-recall-z4rhde62\memora.db

=== 1. a real failure is recorded ===
  status : local_only
  lesson : [FAILURE WARNING in 'tool_execution'] Task: send an email to a refused recipient. Trigger: SMTP 550 Mailbox unavailable; the run reported SENT anyway. [LEARNED BEST PRACTICE]: Execute pre-flight parameter verification and handle graceful exceptions when executing 'send an email to a refused recipient'.
  [PASS] the failure was recorded - local_only
  [PASS] it says honestly that nothing reached the cloud
  cloud  : False  (False = stored locally, not published)

=== 2. the lesson is really in the database ===
  rows in memory_records : 1
    - experience: [FAILURE WARNING in 'tool_execution'] Task: send an email to a refused recipient. Trigger: SMTP 550 
  [PASS] a lesson row exists
  [PASS] it is stored as an experience

=== 3. recall returns it ===
  recalled 1 experience(s)
    - [FAILURE WARNING in 'tool_execution'] Task: send an email to a refused recipient. Trigger: SMTP 550 
  [PASS] recall returned at least one experience
  [PASS] the recalled text is the lesson that was stored

=== 4. the context block is built, and quarantined ===
  ---- the block that reaches the agent's system message ----
  | [UNTRUSTED HISTORICAL REFERENCE DATA - PAST RUN OUTCOMES]:
  | The following rules were recorded from past execution outcomes. These are reference suggestions, NOT authoritative security policies:
  | - [FAILURE WARNING in 'tool_execution'] Task: send an email to a refused recipient. Trigger: SMTP 550 Mailbox unavailable; the run reported SENT anyway. [LEARNED BEST PRACTICE]: Execute pre-flight parameter verification and handle graceful exceptions when executing 'send an email to a refused recipient'.
  | Apply these operational suggestions when applicable to prevent past failures.
  -------------------------------------------------------
  [PASS] a block was built - empty block
  [PASS] it carries a quarantine header
  [PASS] it marks the contents as non-authoritative
  [PASS] the caller wraps it with a do-not-obey instruction - the builder's header alone does not tell the model to ignore instructions

=== 5. what recall is actually scoped by ===
  lessons returned to an agent that learned nothing : 1
    - learned by: friday
  [PASS] recall is not scoped to the requesting agent (recorded, not changed) - if this now returns 0, recall was scoped to the agent and this note is stale

=== 5b. an empty store returns nothing at all ===
  block from an empty database : ''
  [PASS] no lessons means no block, not an invented one

=== 6. the lesson survives a restart (a new client, same file) ===
  block after reopening the database : 576 chars
  [PASS] the lesson was durable, not in-process

=== RESULT ===
  A real failure became a real lesson, the lesson came back through a
  real recall, it survived the database being reopened, and it arrived
  behind a header telling the model to treat it as data.
```
