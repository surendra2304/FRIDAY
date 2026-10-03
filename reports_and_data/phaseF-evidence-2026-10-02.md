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
`python research/repair_trigger_run.py`. Latest run: **29 checks, 0 failures, exit 0.**
(An earlier version of this file said 26. The driver runs 29; the count was
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

### 2.5 One unreachable spec must not cost the pass

An audit found the trigger wrapping `propose` and `review` per-spec but leaving both
`client.post` calls bare. Measured, with a client that fails on its second call:

```
run_once ABORTED with ConnectError
outcomes already gathered for specs 1 and 2 were discarded
```

So a transport blip — the single most likely failure on a free-tier host — turned
into an empty report, which is the one reading nobody can act on. It could also read
as "nothing was broken".

**Fixed.** A failed call is now a *third* kind of outcome, kept distinct from the
other two on purpose: a refusal means the gate answered "no", a declined proposal
means Forge answered "no", and a failed call means **nobody answered**, so that spec
has no result and nothing may be inferred about it. `TriggerOutcome.call_failed` and
`has_result` carry that, the summary line reads `NO RESULT - gate call failed`, and
`render_summary` prints a `no result at all` count plus an `INCOMPLETE PASS` banner
that states the other counts are not evidence the spec was fine. `run_once` also
keeps a net under everything `run_spec` does not handle itself.

A dropped *review* call deliberately keeps the proposal: the gate is then holding a
PROPOSED patch with no review, which is a safe and truthful state, and discarding it
would throw away work that genuinely landed.

**Proven against a real socket**, not a stub that raises: the real `HttpxGateClient`
pointed at a real threaded HTTP server on a real port, which closes the connection
with no response on a chosen call — `RemoteProtocolError: Server disconnected without
sending a response`, which is what a cold start or a cut request actually looks like.
Parametrized over both halves: a dropped propose costs that spec entirely; a dropped
review costs only the review. In both cases the other two specs complete with their
real outcomes and the summary shows `INCOMPLETE PASS`.

### 2.6 A failure must name the party that failed

Probing the fix above turned up two cases where the trigger reported the wrong
thing about itself. Both are fixed; neither was caught by a test that only checked
"the pass completed".

**A payload that could not be built blamed the gate.** The build sits before the
network, so the gate was never asked, yet the outcome said the gate was unreachable
— sending a reader after a service that was not involved. Now recorded as
`failed_party="local"` and rendered `NO RESULT - nothing was submitted; the failure
was local`.

**A reviewer that failed produced no verdict and no warning.** The spec came back
`proposed, review SKIPPED`, which is true and useless: it never appeared in the
incompleteness count, so a pass that could not review something looked like a pass
that had nothing to review. Now counted, named `sentinel`, and its summary line
reads `the reviewer failed, so this repair has no verdict` — while the proposal that
did land is still reported, because it is real.

**A third case turned up while fixing those two**: a proposer that *raises* was
reported identically to a proposer that *declines*. Forge crashing and Forge
answering "no" are different problems needing different fixes, so the crash is now
`failed_party="forge"` and the decline stays a plain `no proposal`.

Every failure mode now names its party, and the summary counts by party so the
reader knows where to look:

```
repair-a: NO RESULT - nothing was submitted; the failure was local (...)
repair-b: NO RESULT - the reviewer failed, so this repair has no verdict (...)
repair-c: NO RESULT - the gate could not be reached (...)
repair-d: NO RESULT - the proposer failed, so no repair was attempted (...)
repair-e: no proposal (the test still fails after the change (exit=1))
repair-f: patch_0006 REVIEWED and waiting on the owner

  specs attempted     : 6
  proposals filed     : 2
  reviews accepted    : 1
  no verdict reached  : 4
  unfinished by party: forge 1, gate 1, local 1, sentinel 1

  INCOMPLETE PASS: 4 of 6 spec(s) reached no verdict. The counts above are NOT evidence that nothing was wrong with them.
```

Proven against a real HTTP server whose own request counter is the evidence: the
local-failure test asserts the server saw **2** requests when three specs ran, which
is only true if the unbuildable spec never reached the network; the reviewer test
asserts the failing spec's proposal still landed while its verdict did not.

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
| 7 | Repair trigger | **A single transport error aborted the whole pass** and discarded every outcome already gathered. | A failed call is now its own outcome (`call_failed`, `NO RESULT`), contained to its spec, counted in the summary with an `INCOMPLETE PASS` banner; `run_once` nets anything else. Proven by dropping a real connection mid-pass (section 2.5). |
| 8 | Repair trigger | **The trigger reported the wrong failing party twice**: a payload that never left the process was blamed on the gate, and a reviewer that failed produced a spec with no verdict that was never counted. A proposer crash was also reported identically to a proposer declining. | `failed_party` names who failed — `local`, `forge`, `sentinel`, `gate` — every no-verdict spec is counted and summarised by party (section 2.6). |

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
| `FRIDAY` self-repair + fleet-truth suites (gate, signatures, HTTP driver, restart, trigger, fleet truth) | **89 passed** |
| `FRIDAY/tests/test_repair_trigger.py` | 32 passed |
| `FRIDAY/tests/test_self_repair_survives_restart.py` | **3 passed** (three real process generations) |
| `research/self_repair_loop.py` (E1 regression, re-run) | 42 assertions, 12 gate steps, **0 failures** |
| `research/repair_trigger_run.py` (F2 driver) | 29 checks, **0 failures**, exit 0 |
| `python -m ruff check` (both repos) | clean |

mypy cannot be run locally — Application Control blocks it on this machine. CI runs
`mypy src/` on every push and is the gate for that. On the heads pushed here it
passed: FRIDAY `3a90ec8` run `36985714594` **success** (ubuntu + windows), Forge
`cbbc298` run `36985664923` **success** (ubuntu + windows).

## 4b. Pushed heads

Refreshed 2026-10-03. The previous version of this table stopped at `02fd988` and
was missing nineteen pushes, which made the record understate both the work and the
risk. Every head from that point is listed, **including the one that was red**.

| Repo | Commit | CI run | Conclusion |
|---|---|---|---|
| Forge | `cbbc298` | `36985664923` | **success** |
| FRIDAY | `22c1a07` (F1) + `3a90ec8` (F2) | `36985714594` | **success** |
| FRIDAY | `26753ab` (CI conclusions doc) | `36986436282` | **success** |
| FRIDAY | `56a9ddf` (durable ledger) + `02fd988` (this file) | `36988808095` | **success** |
| FRIDAY | `93d2af9` | `36989669023` | **success** |
| FRIDAY | `09b42d9` | `36991275067` | **success** |
| FRIDAY | `deb0b41` | `36992622035` | **success** |
| FRIDAY | `17c05af` | `36994068729` | **success** |
| FRIDAY | `f2152c8` | `37015077326` | **success** |
| FRIDAY | `82fd04e` | `37026037117` | **success** |
| FRIDAY | `d8a76f6` | `37034059167` | **failure (ubuntu) / success (windows)** — see below |
| FRIDAY | `eb363b6` (platform gate) | `37034966578` | **success** |
| FRIDAY | `f064ea9` | `37036727328` | **success** |
| FRIDAY | `cd81d6f` | `37038375380` | **success** |
| FRIDAY | `8c16cb8` | `37039662318` | **success** |
| FRIDAY | `ee468eb` | `37043442492` | **success** |
| FRIDAY | `94ee67f` | `37045436000` | **success** |
| FRIDAY | `64a27b5` | `37047676249` | **success** |
| FRIDAY | `9665412` | `37050759056` | **success** |
| FRIDAY | `c8449c5` | `37104234157` | **success** |
| FRIDAY | `7690edb` (F2 caller) | `37105042011` | **success** — 1630 passed |
| FRIDAY | `ecd4fff` (F3 checklist) | `37105256385` | **success** |

### The one red head, and what it was

`d8a76f6` failed on **ubuntu-latest** and passed on windows-latest. This is a real
failure and it was pushed, so it is recorded rather than quietly dropped:

```
AssertionError: the send keystroke was never attempted
AssertionError: the user must be told where to check for the truth
  assert 'Sent folder' in "... (module 'ctypes' has no attribute 'windll') ..."
```

The cause was not the behaviour under test. The Gmail web fallback drives Windows
input through `ctypes.windll`, which does not exist off Windows, so the auto-send
thread raised before the stubbed driver was reached and the assertions were failing
on the absence of the platform rather than on the product.

Fixed in the very next push, `eb363b6`, by gating those cases on `sys.platform != "win32"`.
Every head from `eb363b6` onward is green on both runners.

This is worth stating plainly rather than as a footnote: the suite had been
reporting a green Windows result while a whole platform was running assertions that
could not have passed for the reason they claimed. The fix moved them to the runner
that can actually exercise them.

The earlier FRIDAY run `36974282664` (push `4d45490`, previously still in progress)
has since completed **success**.

The durable-ledger head was verified on **both** CI runners, which matters more
than usual: `tests/test_self_repair_survives_restart.py` starts and kills real
server processes and runs real git, so a green run there is evidence the
restart path works on a clean machine, not just on the one that wrote it.

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
