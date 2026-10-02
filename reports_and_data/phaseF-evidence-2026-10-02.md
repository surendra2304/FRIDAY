# Phase F evidence — 2026-10-02

**Owner:** Surendra · **F1 label: LIVE probes + real CI conclusions. F2 label: LOCAL ONLY.**

Two different labels in one phase, and the difference matters more than anything else in this file.

- **F1** measured the deployed fleet over the public internet. Every row in
  `fleet-truth-20261002T084141Z.{json,md}` came from an HTTP request to a real
  Render service and a real version-control conclusion. That is real.
- **F2** ran the self-repair loop **on this machine**. The gate was a `uvicorn`
  process on a random loopback port, started by the driver script and killed when
  the script exited. **The gate is not a deployed service.** No F2 artefact is
  running anywhere after the driver stops, and nothing in F2 has ever touched a
  deployed Render instance. Any statement that Phase F "deployed autonomous
  self-repair" would be false.

---

## 1. F1 — fleet truth (LIVE)

Full report: `fleet-truth-20261002T084141Z.md` (and `.json`). Reproduce with
`python research/fleet_truth.py`.

Measured 2026-10-02T08:41:41Z:

| | count |
|---|---|
| LIVE (answered 200 **and** carried `evidence_class` + `observed_at`) | **7 / 9** |
| STALE_BUILD (answered 200, evidence fields absent) | 2 — Memora, Cortex |
| UNREACHABLE | 0 |
| CI green on the pushed head | **9 / 9** |

Real in F1:

- The HTTP probes. Seven services answered with a self-labelled evidence class and
  a timestamp; the two that did not are graded `STALE_BUILD` rather than live,
  because a health claim that cannot be falsified is not evidence.
- The CI conclusions, read per repo with the version-control CLI and matched
  against the local HEAD so a green run on an older commit cannot be counted.

Not claimed by F1:

- `LIVE` is a liveness verdict, not a correctness verdict. Nothing here proves any
  service performs its task correctly against a live workload.

## 2. F2 — repair trigger (LOCAL)

Two pieces, both real code, neither deployed.

### 2.1 The trigger — `src/friday/autonomous/repair_trigger.py`

The E1 loop was a proof, not a service: nothing in the running system proposed a
repair or filed a review. This module is what makes the loop reachable, and it is
built around two properties that are enforced structurally rather than by comment:

- **It cannot approve or apply.** The `GateClient` Protocol it depends on has no
  `approve`, no `apply` and no `rollback` method. `HttpxGateClient` has none
  either, and `tests/test_repair_trigger.py` asserts their absence — the type is
  the enforcement. The module's source contains no `owner-decision`, `/apply` or
  `/rollback` endpoint string at all.
- **It never imports a sibling service.** FRIDAY has zero cross-repo imports in
  `src/friday`; peers are spoken to over HTTP. Forge and Sentinel are therefore
  injected as `proposal_factory` / `reviewer_factory`, and a test reads the module's
  AST to keep it that way.

An unattended pass can take a repair to `REVIEWED` and no further. The last step is
the owner's, and it is the only step that is.

22 tests, all passing: `tests/test_repair_trigger.py`.

### 2.2 The driver — `research/repair_trigger_run.py`

Proves the trigger over real HTTP against a real git repository. Run it with
`python research/repair_trigger_run.py`. Latest run: **28 checks, 0 failures, exit 0.**
(An earlier version of this file said 26. The driver runs 28; the count was
understated and is corrected here rather than quietly left.)

What it does, in order, on this machine:

1. Builds a real git repository with a real failing test (`describe()` formats a
   percentage that is 100× too large).
2. Starts the gate as a **separate OS process** — a real `uvicorn` on a real port,
   serving the real `friday.api.server:app`, with `RENDER=1` and `FRIDAY_API_KEY`
   set so the production control-access guard is exercised rather than the loopback
   bypass. The driver imports the gate module nowhere; a test asserts that.
3. Wires in Forge's real `GitSelfRepairProposer` and Sentinel's real
   `SelfRepairReviewer` (with its existing `ApprovalManager` and audit HMAC) and
   drives the trigger. Two specs: one correct fix, and one that is genuinely wrong
   (it drops the `%` sign) which the proposer must decline.
4. Asserts the trigger stopped at `REVIEWED`, called only the two endpoints that
   cannot write, and left the caller's repository untouched — same branch, no repair
   branch, clean tree, broken line intact.
5. Then, as a **different caller**, approves over HTTP, applies, and rolls back.

Observed results from that run:

| Claim | How it was observed |
|---|---|
| Proposal reached `REVIEWED` | gate state `REVIEWED`, 1 review accepted |
| Signature was verified cryptographically | gate `signature_verified: true`; the verifier is reimplemented locally and never imports the signer |
| Wrong candidate refused | "the test still fails after the change (exit=1); no proposal was emitted" |
| Trigger never wrote | only `/api/self-repair/proposals` and `/api/self-repair/patch_0001/review` were ever called |
| Caller's repo untouched | branch still `main`, no `repair/*` branch, `git status --porcelain` empty, file byte-identical to base |
| Owner approval accepted | receipt `ACCEPTED — owner approved; approval is single-use and expiring` |
| **Real apply commit** | receipt commit `15634ddd…` equals `git rev-parse HEAD`; repo on `repair/percent-change`; **4 passed** |
| Real rollback | receipt `ACCEPTED`; broken line restored; test fails again (exit 1) |

### 2.3 Real vs simulated vs local, for F2 specifically

**REAL**

- The repository, the failing test, the branch, and every test invocation: real
  subprocesses, real output, exit codes checked.
- The apply commit and the revert commit: real `git` commits, verified by comparing
  the receipt's commit SHA against `git rev-parse HEAD`.
- The gate in its own OS process, reached only over HTTP, with a real 401 from the
  production control guard when the caller is unauthenticated (proven in E1,
  re-used here via the same server).
- The signature: HMAC over a canonical document, minted by Sentinel's existing
  approval machinery, verified by a verifier that does not import the signer.

**SIMULATED**

- The owner decision is made by the driver as a named caller over HTTP
  (`surendra`), not by a human clicking a button.
- Forge and Sentinel run **inside the driver process**. They are HTTP libraries,
  not servers, so only the gate interactions cross the network boundary. Nothing
  here proves a deployed Forge or Sentinel would behave identically.
- The shared review key and the control key are **test literals** handed to the
  gate by the driver. They are not deployment secrets, and nothing about them
  demonstrates key distribution or rotation in production.
- The trigger is invoked directly by the script. **Nothing yet schedules it** in
  the running service, and no scheduler or `RENDER` worker has been wired to run it.
- The trigger's candidate fixes come from `WatchSpec` literals. There is no
  detector that decides *which* file is broken; that is still missing.

**LOCAL, NOT LIVE**

- The gate is a loopback process. It is **not a deployed service**, has no
  persistent state across the run, and disappears when the driver exits.
- Nothing in F2 has run against `friday-*.onrender.com` or any other deployment.

## 2.4 Durability: the one thing every proof above was blind to

An audit of this phase found a defect that no proof in the repository could see,
because **every one of them ran a single process**.

`SelfRepairGate` held its entire ledger in a `dict` on the instance. Measured,
before the fix, with the real class:

```
instance A proposes  -> ACCEPTED patch_0001 PROPOSED
after a restart, GET     -> None
after a restart, apply   -> REFUSED | NOT_PROPOSED: unknown patch patch_0001
after a restart, rollback-> REFUSED | NOT_PROPOSED: unknown patch patch_0001
```

So on a host that sleeps and redeploys, a `REVIEWED` patch could vanish between
the review and the owner's approval — and, far worse, **a patch that had already
been applied could no longer be rolled back**, with the record of the apply gone.

**Fixed** inside `SelfRepairGate` only: `_restore()` at construction, `_persist()`
on every recorded transition, and a lossless ledger serializer deliberately kept
separate from `RepairRecord.as_dict` (that is the endpoint's summary shape and it
omits the approval's bound fingerprint — the one field that binds an approval to a
patch). `_persist()` is called from `_record()`, which every accept *and* every
refusal funnels through, so there is one place to be right rather than five that
will eventually be missed. Writes are atomic (temp file + `os.replace`).

**Proven by killing real processes** — `tests/test_self_repair_survives_restart.py`,
collected by CI on both runners:

| Process | Does |
|---|---|
| 1 | proposes, and files a signed review that spends approval `appr_restart_1` |
| 2 | **killed.** New process: finds the record still `REVIEWED` with both receipts; a *second* patch reviewed with the *same* approval id is refused `REVIEW_APPROVAL_REPLAYED` — refused by the restored ledger, because this process's own memory has never heard of that id; then owner approval and a real apply commit |
| 3 | **killed.** New process: the record is still `APPLIED` with `consumed: true`, and rollback is accepted — the broken line is back and the reversal is a real commit |

3 tests, 0 failures, ~15s. The receipt trail after the third process reads
`['propose', 'review', 'owner_decision', 'apply', 'rollback']` — the whole
lifecycle, carried across two process deaths.

**What this does not claim**

- **It survives a process restart, a crash, and a free-tier spin-down. It does not
  survive a redeploy onto a fresh container** — the ledger is a file on that
  container's disk. Surviving a redeploy needs a fleet store (Memora/Turso), which
  is separate work and is not claimed here.
- **The deployed gate is still in-memory.** `FRIDAY_SELF_REPAIR_STATE` is not set
  on the Render service, and `FRIDAY_SELF_REPAIR_REPO` is not set either, so
  `_self_repair_gate` is built with no applier and would refuse every apply with
  `NO_CHECKPOINT`. The fix is written, tested and proven locally; it is not live.
  **Exact owner action to make it live:** Render → *friday* → Environment →
  add `FRIDAY_SELF_REPAIR_REPO` (a git checkout on a durable volume, not the
  container disk) and `FRIDAY_SELF_REPAIR_STATE` (a path on durable storage), then
  redeploy. **Verify with:** `curl -s https://friday-zw59.onrender.com/openapi.json | grep -c self-repair`
  for the routes and a propose → review → restart → apply round trip for the ledger.
- Until `FRIDAY_SELF_REPAIR_REPO` exists, the deployed gate cannot apply anything.
  That is a fail-closed outcome, not a hazard, but it means the deployed gate is
  not a working pipeline and must not be reported as one.

## 3. Defects this phase actually found and fixed

Not a list of things that were already right. Each of these was reproduced by a
real run, then fixed, then pinned by a test.

| # | Where | Defect | Fix |
|---|---|---|---|
| 1 | Forge proposer | `git checkout <base_commit>` (a SHA) **detaches HEAD**, so cleanup left the caller's repository on a detached HEAD — every later commit would land nowhere. | `_original_head()` records `(ref, commit)` before the first checkout; `_restore()` returns the caller to exactly where they were, on every path. |
| 2 | Forge proposer | Line 257 called `await self._restore_worktree(repo)`, a method that **did not exist**, and no test referenced it — a branch collision surfaced as `AttributeError`. | One `_cleanup()` used by every path; `RuntimeError` names the collision. |
| 3 | Forge proposer | `keep_branch=True` left the caller parked on the scratch branch, and the "retained" branch did not contain the patch — the fix lived only in a dirty working tree. | The fix is committed on the scratch branch, the caller is returned to their own ref with a clean tree, and the reason names the retained commit. |
| 4 | F2 driver | The reviewer wrote `sentinel.db`, `-wal` and `-shm` **into the repository it was auditing**, because the runner pointed Sentinel's persistence at the repo path. Found by the "working tree was never touched" check failing with three untracked files. | Reviewer state moved to its own directory outside the repo; a check now fails if any `*.db*` appears in the repo. |
| 5 | Repair trigger | A trigger built without a proposer or a reviewer **reported "no proposal" for every spec** instead of failing — indistinguishable, in the summary, from a fleet where nothing was broken. | `TriggerNotConfigured`, deliberately not caught by the per-spec handler, so an inert trigger fails loudly on its first pass. |
| 6 | Repair trigger | A caller was **detached at a commit of their own** and would have been restored onto the default branch — their working tree would have changed underneath them without a word. | Covered by a new Forge test (`test_a_detached_caller_is_returned_to_the_same_commit_not_the_default_branch`). |

Also fixed: the F2 driver originally stopped at `REVIEWED`, so no real apply commit
existed on the F2 surface. It now completes the loop as a distinct owner caller.

And found by audit rather than by a failing test: the gate's in-memory ledger
(section 2.4). It is listed here because a test that never ran would not have
found it, and it was the most consequential defect in the phase.

## 4. Test totals, this phase

| Suite | Result |
|---|---|
| `Forge/tests/unit/` (whole repo) | **294 passed** |
| `Forge/tests/unit/test_selfrepair_proposer.py` | 23 passed |
| `FRIDAY` self-repair + fleet-truth suites (gate, signatures, HTTP driver, restart, trigger, fleet truth) | **79 passed** |
| `FRIDAY/tests/test_repair_trigger.py` | 22 passed |
| `FRIDAY/tests/test_self_repair_survives_restart.py` | **3 passed** (three real process generations) |
| `research/self_repair_loop.py` (E1 regression, re-run) | 42 assertions, 12 gate steps, **0 failures** |
| `research/repair_trigger_run.py` (F2 driver) | 28 checks, **0 failures**, exit 0 |
| `python -m ruff check` (both repos) | clean |

mypy cannot be run locally — Application Control blocks it on this machine. CI runs
`mypy src/` on every push and is the gate for that. On the heads pushed here it
passed: FRIDAY `3a90ec8` run `36985714594` **success** (ubuntu + windows), Forge
`cbbc298` run `36985664923` **success** (ubuntu + windows).

## 4b. Pushed heads

| Repo | Commit | CI run | Conclusion |
|---|---|---|---|
| Forge | `cbbc298` | `36985664923` | **success** |
| FRIDAY | `22c1a07` (F1) + `3a90ec8` (F2) | `36985714594` | **success** |

The earlier FRIDAY run `36974282664` (push `4d45490`, previously still in progress)
has since completed **success**.

## 5. Blocked on the owner

### Cortex redeploy — owner-blocked

- **Why:** auto-deploy is off for this service only.
- **Exact action:** Render dashboard → Cortex service → Manual Deploy → *Deploy latest commit*.
- **Verify:** `curl -s https://cortex-0m7c.onrender.com/health` — expect `evidence_class` **and** `observed_at`.
- **Measured 2026-10-02T08:42:01Z:** `{"status":"UP","timestamp":"2026-10-02T08:42:01.954450","service":"CORTEX API"}` — no evidence fields, hence `STALE_BUILD`.

### Memora redeploy — owner-blocked

- **Why:** auto-deploy is off for this service only.
- **Exact action:** Render dashboard → Memora service → Manual Deploy → *Deploy latest commit*.
- **Verify:** `curl -s https://memora-cavc.onrender.com/health` — expect `evidence_class` **and** `observed_at`.
- **Measured 2026-10-02T08:42:01Z:** `{"status":"healthy","service":"memora-api","database":"healthy",…}` — no evidence fields, hence `STALE_BUILD`.

Neither is a code failure. Both are reachable and healthy; they are running a build
that predates the evidence fields.

### Phase D3 — owner-blocked

- **Why:** no Render API key, deploy hook or UptimeRobot credential is reachable
  from this machine.
- **Exact action:** open each of the nine Render dashboards and UptimeRobot, confirm
  the $0 tier and free-plan status.
- **Verify:** a dated note naming each dashboard and what it showed.

### Not started, deliberately

- **F3** (the owner checklist) has not been started, per the current instruction.
- The trigger is not scheduled anywhere. Wiring it into a running service with a
  real candidate detector is the next piece of work and is **not** done.
- **The durable ledger is not live.** It is written, tested and proven locally;
  the Render service still runs the gate in memory with no applier (section 2.4).
  Owner action is named there with the verify command.

---

_Written 2026-10-02. F1 re-runnable with `python research/fleet_truth.py`; F2
re-runnable with `python research/repair_trigger_run.py`. Neither script contacts a
deployed FRIDAY gate._
