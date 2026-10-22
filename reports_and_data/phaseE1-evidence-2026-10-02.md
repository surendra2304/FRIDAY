# Phase E1 — Gated self-repair: evidence record

**Date of record:** 2026-10-02 · **Owner:** Surendra · **Label: LOCAL (this machine), not LIVE.**

Supersedes the earlier record of the same date, which described the gate as a
"working lock with no one turning the key". That is no longer accurate. The three
services are now wired to each other, the gate verifies Sentinel's verdict
cryptographically instead of trusting a claimed identity, and the whole loop is
driven over real HTTP against a real git repository. Section 8 states plainly
what is still simulated.

---

## 1. What already existed, and what was actually missing

An audit of all three services before writing any code found most of the raw
material already built:

| Piece | Where | State before this phase |
|---|---|---|
| Patch synthesis + application | `Forge/app/recovery/repair.py` (`PatchApplicator`) | existed, sandbox-only, no approval concept |
| Branch / commit / PR / rollback | `Forge/app/execution/git_tool.py` | existed, unused by any pipeline |
| Owner approval, single-use, TTL, fingerprint-bound | `Sentinel/sentinel/core/auth/approvals.py` (`ApprovalManager`) | existed and was sound |
| HMAC signing scheme for audit documents | `Sentinel/sentinel/audit/audit_logger.py` | existed, used only for audit |
| Forge + Sentinel URLs and keys in the orchestrator | `FRIDAY/src/friday/ecosystem/fleet_client.py` | existed |
| **A gate that refuses to apply without a valid owner approval** | — | **did not exist** |

The missing piece was not machinery, it was **the thing that makes the machinery
safe**, and then the connections between the parts. So Phase E1 built the gate,
then built the two agents' ends of it, reusing Sentinel's existing approval and
signing machinery rather than inventing a second approval path.

## 2. The rules the gate enforces

1. **No evidence, no proposal.** A proposal without a named test command that
   actually passed is refused. `"passed": false` is not a weaker claim, it is a
   rejection.
2. **A review must be signed by the party it names.** The gate recomputes the
   HMAC itself, from a key it holds, and never asks who the reviewer claims to
   be. This is the change that closed the loop's weakest link.
3. **A review binds to one patch, one fingerprint, and a short window.** Change a
   byte of code after review and the review no longer applies.
4. **No agent may approve a repair — including FRIDAY.** Implemented as a
   deny-list of agent identities, so an agent added tomorrow is excluded by
   default rather than admitted by omission.
5. **Approvals are single-use and expire** (15 minutes). A replayed apply is
   refused by name (`APPROVAL_CONSUMED`), not lumped in with "never approved".
6. **A patch may only land on content that still matches the review.** If the
   claimed before-text is absent at the pinned base commit, or appears more than
   once, the apply is refused rather than guessed at.
7. **Rollback is always reachable.** Applying records a checkpoint; rollback is a
   real `git revert`, so the reversal is itself an auditable commit.
8. **Every attempt and every refusal emits a receipt.** A pipeline that can only
   report success cannot be audited.
9. **With no review key configured, no review is accepted at all.** The gate
   raises `NO_REVIEW_KEY` rather than falling back to a default key.

Refusals are split into *terminal* (the proposal itself is bad: no evidence,
empty patch, rejected review) and *per-attempt* (bad signature, wrong actor,
stale approval, failed apply). Only terminal refusals end the pipeline, so a
forged review cannot be used to make a patch permanently un-appliable or to make
a half-applied patch un-recoverable.

## 3. The three new modules

| Module | Repo | Lines | What it does |
|---|---|---|---|
| `Sentinel/sentinel/core/selfrepair/reviewer.py` | Sentinel | 300 | Inspects the proposed diff, mints a single-use approval through the **existing** `ApprovalManager`, signs the verdict with Sentinel's **existing** audit HMAC scheme. Raises rather than defaulting if no signing key is configured. |
| `Forge/app/selfrepair/proposer.py` | Forge | 379 | Runs the real test command, branches, applies, runs it again, and **refuses to emit a proposal unless the command genuinely went failing → passing**. Hands the working tree back by default: proposing is not applying. |
| `FRIDAY/src/friday/autonomous/self_repair.py` (amended) | FRIDAY | — | `record_review(patch_id, review: dict)` now takes a signed document and verifies the HMAC with a **locally reimplemented** verifier (it never imports Sentinel's signer). |

The reviewer also had to start returning the `ActionRequest` alongside the
approval, because the approval was bound to a fingerprint that no caller could
otherwise reconstruct. That was a real API gap, found by writing the caller.

## 4. Three real defects found while building it

All three were found by running things, not by reading code.

- **A refused `apply` set the record to `BLOCKED`, which made `rollback`
  unreachable.** A half-applied patch would have become un-recoverable — the
  exact opposite of the point. Fixed by the terminal/per-attempt split above.
- **`git checkout <sha>` does not discard uncommitted changes**, so Forge's
  scratch branch survived cleanup and the working tree stayed dirty. Git also
  refuses to delete the branch you are standing on. Fixed with an explicit
  `reset --hard` + `clean -fd` + `checkout --detach` sequence, consolidated into
  one `_cleanup()` helper because the failure paths had triplicated the buggy
  version.
- **Bytecode staleness.** A repair that does not change file length
  (`a - b` → `a + b`) can land inside one filesystem timestamp tick; Python's
  `.pyc` validation passes and the test runs the **old** code. Reproduced
  standalone: the file was correct on disk and the test still failed. Fixed by
  purging bytecode before the post-change run. Without this, the proposer could
  have reported a repair "verified" that the test never actually exercised.

## 5. Test results

Nothing here is mocked. Every test that touches git builds a real throwaway
repository, makes a real commit, applies through the real `git` binary, and
asserts on real commit hashes. A mocked git would have proved the state machine
but not that a repair can actually be applied and rolled back.

```
tests/test_self_repair_gate.py ................. 18 passed
tests/test_self_repair_review_signature.py ..... 14 passed
tests/test_self_repair_loop_is_over_http.py ....  4 passed
                                              ─────────
                                               36 passed
```

`Sentinel`: `pytest tests/security` → **68 passed** (includes 29 new reviewer tests).
`Forge`: 16 new proposer unit tests.
`ruff check` clean on every touched file.

`tests/test_self_repair_loop_is_over_http.py` is a structural guard on the driver
itself: it parses the driver's AST and fails if the driver imports the gate
module, because a driver that could call the gate directly would print a
convincing transcript while proving nothing about the surface the other agents
actually call.

## 6. End-to-end run — real HTTP, real git, separate processes

`python research/self_repair_loop.py` starts the gate as a **real `uvicorn`
process on a real port** and drives every interaction over real HTTP. The
driver does not import the gate and cannot reach it any other way.

The server is started with `RENDER=1` and a control key, so the transcript
exercises the **production** control-access guard rather than the loopback
bypass. The gate is started with the shared review key, because a keyless gate
accepts no review at all.

Result of the recorded run: **42 assertions passed, 0 failed, exit 0.**
12 gate steps: 5 acceptances, 7 refusals.

| # | Step | Result |
|---|---|---|
| 1 | gate starts as a separate process | server pid 3752, driver pid 13204, `overall=healthy evidence_class=process_liveness` |
| 2 | **unauthenticated** caller files a proposal | **401** `A valid FRIDAY control API key is required.` |
| 3 | Forge proposes: real branch, real test before and after | test `..FF` → `4 passed`; tree handed back, no branch left behind |
| 4 | proposal with no test evidence | **REFUSED** — `NO_TEST_EVIDENCE` |
| 5 | Forge files the real proposal over HTTP | **ACCEPTED** — records the passing command |
| 6 | forged review (all-zero signature) | **REFUSED** — `BAD_REVIEW_SIGNATURE` |
| 7 | genuine review signed for a different patch | **REFUSED** — `REVIEW_WRONG_PATCH` |
| 8 | Sentinel reviews the real patch | cleared, approval `appr_selfrepair_…` `approved`, signature `ed17fadd…` |
| 9 | verdict flipped to `block` after signing | **REFUSED** — `BAD_REVIEW_SIGNATURE` |
| 10 | genuinely signed review filed over HTTP | **ACCEPTED** — `signature_verified: true`, state `REVIEWED` |
| 11 | same review replayed against another patch | **REFUSED** — `REVIEW_WRONG_PATCH` |
| 12 | `friday` / `forge` / `sentinel` each try to approve | **REFUSED** — `WRONG_APPROVER` |
| 12 | `surendra` approves | **ACCEPTED** — `appr_0004`, single-use, expiring |
| 13 | apply | **ACCEPTED** — real commit `3b443839…` on `repair/percent-change` |
| 14 | apply again | **REFUSED** — `APPROVAL_CONSUMED` |
| 15 | run the real test on the applied tree | **4 passed** |
| 16 | rollback | **ACCEPTED** — revert commit `095f12cf…`, test fails again |

Verbatim receipts from that run:

```json
{"proposed_by": "forge", "base_commit": "838fb3eaead7de2d4da8b2d07edc81e3b16e181b",
 "test_command": "\"...python.exe\" -m pytest test_percent_change.py -q", "files_touched": 0}

{"branch": "repair/percent-change",
 "branch_point": "a7e6a1e4661ec92784e938d07da76c2cdb675f0e",
 "applied_commit": "3b443839ae179ee1496083cd403b2ed72d3c1c52",
 "rollback_point": "a7e6a1e4661ec92784e938d07da76c2cdb675f0e",
 "files_touched": 1}

{"reverted_commit": "3b443839ae179ee1496083cd403b2ed72d3c1c52",
 "revert_commit": "095f12cff00edd10699aaa7c724f55b429705412",
 "branch": "repair/percent-change"}
```

The test output before the apply and after the rollback, both real:

```
..FF   test_describe_formats_a_percentage: assert '1000.00%' == '10.00%'
....   4 passed
```

So the sequence is genuinely: a real failing test → a real one-line patch that
makes it pass → a cryptographically verified review → a real apply commit →
**the same test failing again** after a real revert commit.

The proposer also refused a *wrong* candidate fix during development, when the
fixture's replacement code was itself buggy. That refusal is the honesty
property working, not a limitation.

## 7. API surface

All six routes sit behind the existing `_require_control_access` guard, and each
additionally sits behind the gate's own rules — the two layers are independent,
and the gate's rules hold even if a caller reaches it another way.

```
POST /api/self-repair/proposals
POST /api/self-repair/{patch_id}/review
POST /api/self-repair/{patch_id}/owner-decision
POST /api/self-repair/{patch_id}/apply
POST /api/self-repair/{patch_id}/rollback
GET  /api/self-repair/{patch_id}
```

`/review` carries the signed document verbatim, so Sentinel does not have to
reshape its own output. The applier is configured by `FRIDAY_SELF_REPAIR_REPO`;
unset, the gate holds proposals and approvals but refuses every apply with
`NO_CHECKPOINT` rather than pretending to have applied something.

## 8. What is real and what is still simulated — stated plainly

**Real, measured on this machine:**

- a real git repository, a real failing test, a real branch and real commits;
- Forge running the real test command before and after, and refusing to propose
  unless the command genuinely went failing → passing;
- Sentinel signing with its existing audit HMAC scheme, and the gate verifying
  that signature with a verifier that never imports the signer;
- the control-access guard refusing an unauthenticated caller with a real 401;
- the gate in a genuinely separate OS process, reached only over real HTTP;
- a real apply commit and a real revert commit, with the test observed passing
  and then failing again.

**Simulated, and labelled as such:**

- **The owner approval is a named caller over HTTP, not a human clicking.** The
  run approves as `"surendra"` from the driver. The gate's rule is that no agent
  identity may approve; it is not that a person must.
- **The shared review key and control key are test literals in the driver**, not
  deployment secrets. In deployment both come from the environment; the driver
  writes them into the server process's environment and labels them as literals.
- **Forge and Sentinel run inside the driver process.** They are libraries that
  speak HTTP rather than servers, so what crosses the network boundary here is
  every gate interaction. The driver says so in its own module docstring.
- **LOCAL, not LIVE.** Nothing here was exercised against the deployed FRIDAY,
  Forge or Sentinel on Render.
- **No autonomous trigger.** Nothing calls this pipeline on a schedule or on a
  failure; it is driven only by the explicit request at step 3.
- **The reviewer's hazard checks are a fixed rule set**, not a learned or
  exhaustive security analysis. It blocks hardcoded credentials, `eval`, `exec`,
  `subprocess`/`os.system`/`shell=True`, outbound network, `chmod 777`, and
  test-suppression markers. A hazard outside that list would pass review.
