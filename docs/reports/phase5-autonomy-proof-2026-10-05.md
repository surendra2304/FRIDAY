# Phase 5 — proof of the autonomous brain, and what remains unproven

**Date:** 2026-10-05
**Branch:** `arena/01a10cba-friday`
**Owner's standing instruction this phase:** *"Passing tests doesn't mean the agent
is working flawlessly. You must test it in real world and at extreme pressures."*

Every claim below was produced by a command run on this machine, and the output is
quoted. Nothing here is inferred from reading code. Where something could not be
run, it is labelled **CONFIGURED-BUT-UNVERIFIED** with the reason.

---

## 1. The headline: an unattended repair, on a real repository, start to finish

The proof environment is a genuine repository at `/tmp/handsfree` (not a fixture, not
a mock), containing a real defect:

```
$ python -m pytest -q          # in /tmp/handsfree
FAILED tests/test_calc.py::test_add_all_sums - NameError: name 'totl' is not defined
1 failed in 0.01s
```

`/tmp/handsfree/conftest.py` puts `src/` on the path, so the repository is
self-importable and the reflex runs its real pytest against it.

### Pass 1 — key configured, no mandate in force

```
$ FRIDAY_REFLEX_REPO=/tmp/handsfree FRIDAY_AUTONOMY_KEY=… \
  FRIDAY_SELF_REPAIR_REVIEW_KEY=… python -m friday --reflex-run tests

autonomy: AWAITING_MANDATE
-> AWAITING_MANDATE | approve | The repair is reviewed, proven and one command
   from done: no active mandate is in force. Grant standing autonomy with
   `friday --grant-autonomy`, or approve this patch directly with
   `friday --approve-repair <patch_id>`.
```

The tree was untouched: `git log` still showed only the starting commit. This is
the refusal the owner sees when autonomy has not been granted — detection,
diagnosis and proof all happened, and nothing was applied.

### The mandate

```
$ python -m friday --grant-autonomy --autonomy-hours 1 --autonomy-scope source_repair

mandate: mandate_1791222626_cb5c24
scopes:  ['source_repair']
paths:   ['src/**', 'tests/**', 'config/**', 'scripts/**', 'docs/**']
expires: 2026-10-05T18:50:26.189177+00:00
```

### Pass 2 — unattended

```
$ python -m friday --reflex-run tests

autonomy: ACTIVE
incidents: 1 | acted_on: 1
-> RESOLVED | propose_review_approve_apply_verify | Repaired src/friday/calc.py
   unattended: the failing test now passes on the real tree.
   Patch patch_0002 on branch reflex/test_failure-1791222629.
```

What actually landed, from the repository itself:

```
$ git log --oneline
7118246 repair(patch_0002): `totl` is not defined; the only near-miss name defined
        in this file is `total`, so the reference is a typo of it.
4afec36 the broken starting point

$ git show --name-only --pretty=format: 7118246
src/friday/calc.py                      # exactly one file, nothing else

$ git show HEAD -- src/friday/calc.py
-    return totl
+    return total

$ python -m pytest -q
1 passed in 0.00s
```

### Pass 3 — the rollback, which is the only safety net

The owner chose maximum autonomy, so the post-apply check *is* the safety net. A
deliberate probe repository was built whose failing test **passes inside the
sandbox and fails on the real tree** — the sandbox copy has no `.git`, so a test
that asks "am I inside a git checkout?" reverses its own answer:

```
$ python -m friday --reflex-run tests

-> ROLLED_BACK | apply_then_rollback
   The repair passed in the sandbox but failed on the real tree, so it was rolled
   back automatically. Rollback receipt: ACCEPTED.
   rollback: {'step': 'rollback', 'outcome': 'ACCEPTED',
              'detail': 'repair reverted; the reversal is itself a commit',
              'evidence': {'reverted_commit': '23ca59cb00ed6819411bd5cfd122e5603eb4a9ab',
                           'revert_commit':   '72cec04b5a91addae1a488017797c204353ed93f',
                           'branch': 'reflex/test_failure-1791222698'}}

$ git log --oneline
72cec04 Revert "repair(patch_0004): `wrod` is not defined; …"
23ca59c repair(patch_0004): `wrod` is not defined; …

$ grep -n "return wrod" src/friday/probe.py
16:    return wrod                    # the tree is exactly as it was
```

An unattended change that survived the sandbox and failed in production was undone
by the agent itself, as a real revert commit, with the receipt saying so.

---

## 2. What the real runs found — defects no test had caught

| # | Defect | Evidence from the real run | State |
|---|---|---|---|
| 1 | The repair commit ran `git add -A`, so an unattended fix committed the reflex brain's own `gate_state.json` and a `.pyc` beside the code | `git status` in the harness showed `M gate_state.json`, `M src/friday/__pycache__/calc.cpython-311.pyc` after a "clean" repair | **FIXED** — `GitRepairApplier.commit_touched` stages exactly the files the applier rewrote and refuses when it touched none; `tests/test_repair_commit_scope.py` (4 tests) |
| 2 | A transport that accepted a connection and never answered hung the dispatch forever | the pressure suite's hung-transport test never returned | **FIXED** — `Mesh.request_timeout` (default 30 s) bounds every send; a timeout is `UNREACHABLE`, by the clock |
| 3 | The breaker counted one failure per *dispatch*, so five dead attempts were one measurement and the circuit opened far later than configured | the pressure test asserted 5, measured 2 | **FIXED** — one measurement per attempt, single-sourced in `_record`; measured 3→3, 5→5, healthy→0 |
| 4 | Eight unreachable peers were reported as `{"status": "OBSERVED", "responses": 8}`; every probe called a connection error `DEGRADED` | the audit's live run, reproduced in `tests/test_peer_evidence_inversion.py` | **FIXED** — probes report `UNREACHABLE`; the controller counts answers, not objects, and names the unreachable peers |
| 5 | Approval authority came from a deny-list of fifteen agent names, so any unlisted name — including a future agent — could approve a repair, and that path needs no key | static finding (BUG-011), pinned by `tests/test_owner_identity_is_positive.py` | **FIXED** — owner identity is positive (`FRIDAY_USER_NAME` / `owner`), with the agent namespace as a second refusal |
| 6 | The loop's own repeat-guard notices were written to long-term memory and recalled into unrelated conversations | the audit's live recall of `Error: Duplicate tool call ID 'tc1' ignored.` | **FIXED** — `is_non_informative_tool_notice` refuses exactly those notices at the write path; they stay in the log |
| 7 | A single hung test consumes the detector's whole-suite budget (900 s default) before the suite gives up | the sleeping-test test measured 120.28 s against a 120 s expectation; the detector then timed out correctly at its configured budget | **BY DESIGN, per-test bound is a candidate improvement** — `IncidentDetector(test_timeout=…)` does bound the suite, and reports `did not finish within Ns`; the pressure test now proves that with a 3 s budget |

---

## 3. Extreme-pressure results

`tests/test_extreme_pressure.py` — **23 tests, 23 passed in 80 s** (was 19/23 before
the defects above were fixed; the four red ones were resolved by fixing three real
defects and correcting two tests whose premises the runs disproved).

What holds under hostility, each of these measured:

- **Hung peer** — a transport that never returns is `UNREACHABLE` by the clock.
- **Garbage** — 10 MB of junk and HTML-instead-of-JSON are `UNVERIFIED`, never absorbed.
- **Impersonation** — a receipt naming another action never completes a dispatch.
- **Concurrency** — 200 concurrent dispatches each return exactly one typed outcome,
  and a broken `on_outcome` listener does not take a dispatch down.
- **Memory under load** — 5000 episodes with 50 corrupt lines still recall in <5 s;
  the store stays bounded under a 500-episode flood.
- **60 agents × 5 writes across 60 threads** — 300/300 writes, zero lost.
- **Eight simultaneous faults in one real repository** — detected in a single scan,
  and nothing applied without a mandate.
- **Mandates** — expired, wrong-scope, path-escaping and tampered mandates are all
  refused; `FILE_NOT_PERMITTED` even for `../../etc/passwd` and
  `/home/user/.ssh/id_rsa`.
- **Drift** — a file edited between review and apply is refused, not guessed at.
- **Unproven patches** — a patch with no failing→passing evidence can never be approved.

Whole suite after all of the above, on this machine:

```
$ python -m pytest -m "not live and not hardware and not windows" -q
1935 passed, 6 skipped, 23 deselected in 174.63s

$ python -m ruff check src/ tests/     → All checks passed!
$ python -m mypy src/                  → Success: no issues found in 458 source files
```

### The scheduled loop, running unattended

`run_forever()` was designed to sleep first and then work; this phase measured it.
With `FRIDAY_REFLEX_INTERVAL_SECONDS=60`, after 75 s of real time:

```
reflex repo: /tmp/handsfree
interval: 60 s | enabled: True
status after 75s: COMPLETED | autonomy: {'status': 'AWAITING_MANDATE', …}
```

One scheduled pass ran by itself, found the fault, and — with the ledger empty —
prepared and proved the repair without applying it. The tree was unchanged.

### The fleet, with no egress

```
$ python -m friday --reflex-run fleet
incidents: 8 | counts: {'ESCALATED': 8}
-> ESCALATED | reconnect_then_mesh | inference | inference did not answer after
   2 attempt(s). Escalated to the mesh: a peer that cannot be reached from here
   may still be reachable from another agent.
```

Eight unreachable peers produce eight honest `ESCALATED` outcomes — never a claim
that a peer is degraded, never a fabricated success.

---

## 4. REAL vs CONFIGURED-BUT-UNVERIFIED

| Capability | State | The evidence, or the reason it is unverified |
|---|---|---|
| Detect → diagnose → sandbox-prove → review → gate → apply → verify, unattended | **REAL** | `/tmp/handsfree`, mandate `mandate_1791222626_cb5c24`, commit `7118246`, post-apply test passes |
| Refusal without a mandate (`AWAITING_MANDATE`, tree untouched) | **REAL** | pass 1 above |
| Automatic rollback when the real tree rejects a sandbox-proven patch | **REAL** | `ROLLED_BACK`, revert commit `72cec04`, file byte-identical to before |
| Repair commit scope (only the repaired file) | **REAL** | `git show --name-only 7118246` → `src/friday/calc.py` |
| Standing-mandate issuance, expiry, revocation, scope and path enforcement | **REAL** | `--grant-autonomy`, `--autonomy-status`, `--revoke-autonomy`; refusal matrix in the pressure suite and `tests/test_autonomy_mandate.py` |
| Owner-only approval (positive identity) | **REAL** | `tests/test_owner_identity_is_positive.py`; future agents refused |
| Reflex brain on a schedule inside a running service | **REAL** | measured above (one pass at 60 s interval); `run_forever` sleeps first by design |
| Mesh/mind/memory cognition layer | **REAL (in-process)** | 1893+ tests, incl. the pressure suite; `LocalReviewer` round-trips through the real gate |
| Live peer calls: the eight cloud agents | **CONFIGURED-BUT-UNVERIFIED** | This sandbox has **no egress**: `curl https://example.com` → HTTP 000, and a live peer call dies with `TLS/SSL connection has been closed`. The contracts, transports, receipts and the in-process `ContractTransport` harness are real and tested; no live peer was reached from here. Run `python -m friday --reflex-run fleet` on a machine with egress and compare with the eight `ESCALATED` outcomes recorded above. |
| Peer task *delegation* (as opposed to health probing) | **CONFIGURED-BUT-UNVERIFIED / not built** | BUG-004 remains open: the `ask_*` methods read health endpoints. A typed task channel (envelope in, receipt out) is roadmap item 2. Nothing here claims a peer executed a task. |
| Semantic memory recall | **CONFIGURED-BUT-UNVERIFIED** | Lexical JSONL recall is real and tested; the semantic path needs an embedding provider that is not configured here. |
| The 8 peer agents' own brains | **NOT BUILT (owner's choice)** | `friday_side` was chosen: FRIDAY-side brain plus a local contract harness, awaiting machines with egress. |
| `SelfImprovementWorkflow` end-to-end | **CONFIGURED-BUT-UNVERIFIED** | The registered tools `self_develop`/`self_repair` are real and in the catalogue; the workflow itself is not registered in a live tool path, and its Phase-31 test exercises mocks. Its README row has been corrected. |
| Live cloud LLM providers | **CONFIGURED-BUT-UNVERIFIED** | No egress; with no provider reachable the rule patcher still repairs what it recognises, and the loop reports `NO_FIX_KNOWN` rather than inventing a fix (observed: `text.uper()` → no candidate). |
| `/api/android` duplicate routes (BUG-006) | **UNVERIFIED** | Not exercised this phase. |

---

## 5. What is still missing, ranked

1. **Capability synthesis does not reach the gate.** `capability.py` can plan and
   verify a new tool, and then stops; it never calls `MandateAuthority` or
   `SelfRepairGate`, so a capability FRIDAY has never had cannot be carried through
   the same proof/apply path as a repair. The observed symptom in the real world:
   `text.uper()` (a typo of a *builtin* method) produced `NO_FIX_KNOWN`, because the
   rule patcher only knows names defined in the file and the model patcher needs
   egress. Fix: wire the gate, and extend the rule patcher to builtin/attribute
   near-misses so the brain has a real fallback when the model cannot be reached.
2. **Delegation is not delegation (BUG-004).** The peer channel must be a typed task
   envelope with a receipt and a completion verifier; a health payload is not a
   completed task.
3. **Failure responses return HTTP 200 (BUG-012)** and `_shared_client` is never
   closed (BUG-013) — small, real, and cheap to fix.
4. **Config and packaging truth (BUG-007, BUG-008, BUG-009):** inference defaults,
   two sources of truth for `autonomous_mode`, and packaging.
5. **Retire the false-green fixture (BUG-003 remainder) and the committed run
   artifacts (BUG-016).** Either register `SelfImprovementWorkflow` in a real tool
   path with honest evidence, or delete the workflow and keep only the tools; and
   move `reports_and_data/` to external storage or delete it.

Also worth doing, in the same pass: bound a single test inside the detector (item 7
above) so one sleeping test cannot consume the whole suite budget.

---

## 6. How to reproduce any of this

```bash
# the whole truth, in one command
python -m pytest -m "not live and not hardware and not windows" -q

# the hostile conditions
python -m pytest tests/test_extreme_pressure.py -q

# an unattended repair, on a real repository you own
export FRIDAY_REFLEX_REPO=/path/to/a/real/repo
export FRIDAY_MIND_DIR=$FRIDAY_REFLEX_REPO/minds          # optional
export FRIDAY_SELF_REPAIR_STATE=$FRIDAY_REFLEX_REPO/gate_state.json
export FRIDAY_AUTONOMY_LEDGER=$FRIDAY_REFLEX_REPO/mandates.json
export FRIDAY_SELF_REPAIR_REVIEW_KEY=<review-key>
export FRIDAY_AUTONOMY_KEY=<owner-key>                    # never commit this
python -m friday --reflex-run tests                       # without a mandate: refuses
python -m friday --grant-autonomy --autonomy-hours 1 --autonomy-scope source_repair
python -m friday --reflex-run tests                       # now it acts, and rolls back on regression
python -m friday --revoke-autonomy all
```

Never commit the keys. If a key is ever found in a commit, rotate it immediately.
