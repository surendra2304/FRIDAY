# Phase E1 — Gated self-repair: evidence record

**Date of record:** 2026-10-02 · **Owner:** Surendra · **Label: LOCAL (this machine), not LIVE.**

Commit `62ca96b`. The pipeline below was built, tested, and driven end-to-end
**on this machine against a real git repository and a real HTTP server.** It is
**not** yet connected to the live Forge and Sentinel deployments, and nothing here
claims that it is. See "What is not wired" at the end.

---

## 1. What already existed, and what was actually missing

An audit of all three services before writing any code found most of the raw
material already built:

| Piece | Where | State before this phase |
|---|---|---|
| Patch synthesis + application | `Forge/app/recovery/repair.py` (`PatchApplicator`) | existed, sandbox-only, no approval concept |
| Branch / commit / PR / rollback | `Forge/app/execution/git_tool.py` | existed, unused by any pipeline |
| Owner approval, single-use, TTL, fingerprint-bound | `Sentinel/sentinel/core/auth/approvals.py` (`ApprovalManager`) | existed and was sound |
| Forge + Sentinel URLs and keys in the orchestrator | `FRIDAY/src/friday/ecosystem/fleet_client.py` | existed |
| **A gate that refuses to apply without a valid owner approval** | — | **did not exist** |

The missing piece was not machinery, it was **the thing that makes the machinery
safe**. Forge could synthesise a patch and Sentinel could hold an approval, but
nothing connected the two: nothing bound an approval to the *specific patch* it
authorised, nothing stopped the agent that would apply the change from approving
it, and nothing guaranteed a repair could be undone.

So Phase E1 built the gate, not another agent.

## 2. The rules the gate enforces

1. **No evidence, no proposal.** A proposal without a named test command that
   actually passed is refused. `"passed": false` is not a weaker claim, it is a
   rejection.
2. **The proposer never reviews itself.** Only `sentinel` may file a review.
3. **No agent may approve a repair — including FRIDAY.** FRIDAY is the component
   that would carry the change out, so approving its own repair is exactly the
   case the gate must refuse. Implemented as a deny-list of agent identities, so
   an agent added tomorrow is excluded by default rather than admitted by omission.
4. **An approval binds to the exact patch.** It is a SHA-256 over the file path,
   the before-text and the after-text. Change one byte of code after approval and
   the approval no longer applies. Rewording the *rationale* does not void it,
   because prose is not payload.
5. **Approvals are single-use and expire** (15 minutes). A replayed apply is
   refused by name (`APPROVAL_CONSUMED`), not lumped in with "never approved".
6. **A patch may only land on content that still matches the review.** If the
   claimed before-text is absent at the pinned base commit, or appears more than
   once, the apply is refused rather than guessed at.
7. **Rollback is always reachable.** Applying records a checkpoint; rollback is a
   real `git revert`, so the reversal is itself an auditable commit.
8. **Every attempt and every refusal emits a receipt.** A pipeline that can only
   report success cannot be audited.

## 3. Two real defects found while building it

Both were found by writing the tests, not by reading the code, and both are worth
recording because one is a genuine safety hole:

- **A refused `apply` set the record to `BLOCKED`, which made `rollback`
  unreachable.** A half-applied patch would have become un-recoverable — the exact
  opposite of the point. Fixed by splitting refusals into *terminal* (the proposal
  itself is bad: no evidence, empty patch, rejected review) and *per-attempt*
  (wrong actor, stale approval, failed apply). Only terminal refusals end the
  pipeline.
- **`friday` was missing from the approver deny-list.** The first version blocked
  `forge` and `sentinel` but not FRIDAY itself, so the applying agent could have
  approved its own repair. Now denied by role, along with every other agent.

## 4. Test results

`pytest tests/test_self_repair_gate.py` → **18 passed**, `ruff check` clean.

These are not mocked. Every test builds a real throwaway git repository, makes a
real commit, applies through the real `git` binary, and asserts on real commit
hashes. A mocked git would have proved the state machine but not that a repair can
actually be applied and rolled back.

```
tests/test_self_repair_gate.py ... 18 passed in 7.27s
```

`pytest tests/test_remote_control_auth.py` → 2 failed. **Verified pre-existing**,
not caused by this change: `git stash` A/B at HEAD produces the identical 2
failures. They depend on a non-example `FRIDAY_API_KEY` being present in the
environment.

## 5. End-to-end run — real HTTP, real git

A real `uvicorn friday.api.server:app` was started on `127.0.0.1:8765` against a
throwaway git repository whose single file was deliberately wrong
(`def add(a, b): return a - b`), and the pipeline was driven with `curl`. Every
response below is verbatim.

| # | Call | Result |
|---|---|---|
| 0 | propose with `{"passed": false}` | **REFUSED** — `NO_TEST_EVIDENCE: proposal arrived without a named test command that passed` |
| 1 | propose with a passing command | **ACCEPTED** — `PROPOSED`, receipt `files_touched: 0` |
| 2 | review as `forge` | **REFUSED** — `WRONG_REVIEWER: reviewer was 'forge'` |
| 3 | review as `sentinel` | **ACCEPTED** — `REVIEWED` |
| 4 | approve as `friday` | **REFUSED** — `WRONG_APPROVER: 'friday' is an agent, not the owner; no agent may approve a repair` |
| 5 | apply before owner approval | **REFUSED** — `NOT_APPROVED: state is REVIEWED; nothing may be applied without owner approval` |
| 6 | approve as `surendra` | **ACCEPTED** — `APPROVED`, approval bound to fingerprint, expiring |
| 7 | apply | **ACCEPTED** — `applied on branch repair/e2e` |
| 9 | apply again (replay) | **REFUSED** — `APPROVAL_CONSUMED: approval was already used` |
| 10 | rollback | **ACCEPTED** — `repair reverted; the reversal is itself a commit` |

The apply receipt, verbatim:

```json
{"branch": "repair/e2e",
 "branch_point": "df483b6e3c48e58649d04604ad00438d24663756",
 "applied_commit": "87681adaee2da359e4c0156ec63f063d34af275a",
 "rollback_point": "df483b6e3c48e58649d04604ad00438d24663756",
 "files_touched": 1}
```

**The real repository, after the apply:**

```
branch: repair/e2e
file:   def add(a, b):     return a + b
log:
  87681ad repair(patch_0002): add() subtracts; the operator is wrong
  df483b6 initial
```

**The real repository, after the rollback:**

```
branch: repair/e2e
file:   def add(a, b):     return a - b
log:
  5f2df9f Revert "repair(patch_0002): add() subtracts; the operator is wrong"
  87681ad repair(patch_0002): add() subtracts; the operator is wrong
  df483b6 initial
```

The repair branched from the pinned commit, changed exactly one file, and the
reversal left the reviewed content intact with the whole history intact. The
approval was consumed exactly once.

## 6. API surface added

All six routes sit behind the existing `_require_control_access` guard, and each
also sits behind the gate's own rules — the two layers are independent, and the
gate's rules hold even if a caller reaches it another way.

```
POST /api/self-repair/proposals
POST /api/self-repair/{patch_id}/review
POST /api/self-repair/{patch_id}/owner-decision
POST /api/self-repair/{patch_id}/apply
POST /api/self-repair/{patch_id}/rollback
GET  /api/self-repair/{patch_id}
```

The applier is configured by `FRIDAY_SELF_REPAIR_REPO`. With it unset the gate
holds proposals and approvals but refuses every apply with `NO_CHECKPOINT` rather
than pretending to have applied something.

## 7. What is not wired — stated plainly

- **Not connected to live Forge or Sentinel.** Forge does not yet *emit* proposals
  to this endpoint, and Sentinel does not yet *file* its review through it. Both
  sides have the capability; the call is not made. The end-to-end run above used a
  curl in place of each agent, and that is exactly what it proves — the gate
  works — and no more.
- **No autonomous trigger.** Nothing calls this pipeline on a schedule or on a
  failure. It is driven only by an explicit request.
- **LOCAL, not LIVE.** Verified on this machine. Not exercised against a deployed
  FRIDAY.
- **No Sentinel policy evaluation inside the gate.** A "clear" review is taken at
  face value; the gate binds and checks it but does not itself judge security. That
  judgement belongs to Sentinel, and until the call is wired, the weakest link in
  this pipeline is a human typing `"sentinel"` into the review endpoint. The
  fingerprint binding limits the damage — an approval still cannot be reused for
  different code — but the review's authenticity is asserted, not verified.

**The next real step is not more code.** It is making Sentinel's review arrive over
its own authenticated API rather than as a caller-supplied actor name, and having
Forge post proposals from a real task. Both are one client each.
