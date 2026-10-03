# Phase F3 — Owner checklist

**Written:** 2026-10-03 · **Owner:** Surendra · **Status:** this phase was NOT STARTED until now.

Every item below is an action only the owner can take. None of them can be
finished by writing code, which is exactly why they kept turning back into work
that looked finished. Each one states what was verified, what to do, and the
command that proves it worked.

Nothing here is a guess. Where a claim needed checking, the check and its result
are recorded. Where something is unverified, it says so.

---

## 1. Memora and Cortex are running a build older than their own source

**Phase D1, "truth in cloud" — 2 of 3 services done. This is the blocker.**

`python research/fleet_truth.py` re-measured the fleet on 2026-10-03 and returned
**7 of 9 LIVE, Memora and Cortex STALE_BUILD, 0 UNREACHABLE, CI green 9/9.**
That is the honest state: two services answer HTTP 200 while running code that
predates their own repository.

`STALE_BUILD` means precisely one thing, and it is not "unhealthy":

> the service answered `200` but its `/health` did not carry the
> `evidence_class` and `observed_at` fields.

Verified on 2026-10-03 — this is **a redeploy, not a code change**:

| repo | pushed head | `/health` in that source | local vs origin |
|---|---|---|---|
| Cortex | `dfb37ab` | emits `evidence_class: process_liveness` + `observed_at` | identical, clean |
| Memora | `e986aea` | emits `evidence_class: server_live_probe` + `observed_at` | identical, clean |

Both repositories already contain the fix, already on `main`, already pushed,
already green in CI. **Nothing is being written for this item.** The deployed
images are simply older than the commits.

**To do**

1. Render dashboard → service **memora** → *Manual Deploy* → **Clear Build Cache and Deploy**.
2. Render dashboard → service **cortex** → *Manual Deploy* → **Clear Build Cache and Deploy**.
   Clear the cache specifically. Both use `runtime: docker`, and a cached layer is
   the usual reason a rebuild still serves the old binary.
3. Wait for both to report healthy.

**To prove it**

```bash
python research/fleet_truth.py
```

Both rows must read `LIVE`. Until they do, D1 is still 2 of 3. A row that reads
`STALE_BUILD` again after a deploy means the image is still old — check the
deploy log, not the dashboard badge.

---

## 2. The unattended repair loop is off in the cloud because five keys are unset

**Phase F2.** The loop itself is now real and measured: `feat(autonomous)` in this
repo wired it into the running service, and
`python research/autonomous_repair_loop_run.py` drives it end to end — real
repository, real failing test, real proposer subprocess, real HTTP gate, real
signature verified, stops at the owner gate, leaves the working tree untouched.

It is **inert in the cloud by design**, and says so rather than pretending:

```json
{ "status": "NOT_CONFIGURED",
  "missing": ["FRIDAY_SELF_REPAIR_TRIGGER_ENABLED", "FRIDAY_SELF_REPAIR_WATCHLIST",
              "FRIDAY_SELF_REPAIR_GATE_URL", "FRIDAY_SELF_REPAIR_GATE_KEY",
              "FRIDAY_SELF_REPAIR_REVIEW_KEY"] }
```

That output is from a real HTTP request to the running service on 2026-10-03, not
a description of one. An autonomous repair loop should never be something a
deployment acquires by being redeployed.

**Before enabling it, read this.** The loop proposes and gets a review filed. It
**cannot approve, apply, or roll back** — that is enforced by the absence of those
calls, and a test asserts it. Turning it on lets the fleet write proposals into
the gate. It cannot write into a repository. If you want the *other* half — the
owner decision and the apply — that is a separate, deliberate act through the
existing `/api/self-repair/{patch_id}/...` endpoints.

**To do — set on the Render service `friday`:**

| key | value | note |
|---|---|---|
| `FRIDAY_SELF_REPAIR_TRIGGER_ENABLED` | `1` | without this the loop never fires |
| `FRIDAY_SELF_REPAIR_WATCHLIST` | path to a JSON file | **must exist in the image** |
| `FRIDAY_SELF_REPAIR_GATE_URL` | the gate's base URL | |
| `FRIDAY_SELF_REPAIR_GATE_KEY` | the control key | signs the HTTP call to the gate |
| `FRIDAY_SELF_REPAIR_REVIEW_KEY` | the shared review key | **a different secret from the control key** |
| `FRIDAY_SELF_REPAIR_TRIGGER_INTERVAL_SECONDS` | optional, default `900` | |

`FRIDAY_SELF_REPAIR_REVIEW_KEY` must be the value the gate verifies Sentinel's HMAC
against. Setting it to the control key makes **every review come back `REFUSED`**,
which reads like Sentinel rejecting the repair. That is not what it means — it was
found by running the loop for real, not by reading it.

**Also unset in the cloud, and needed by the existing E1 endpoints** (these are
independent of the loop):

- `FRIDAY_SELF_REPAIR_REPO` — the repository the gate is allowed to touch.
  Without it `GitRepairApplier` is `None` and apply cannot work at all.
- `FRIDAY_SELF_REPAIR_STATE` — where gate records are written. Without it the gate
  holds records in memory and they are lost on restart, so a restart cannot be
  distinguished from a clean slate.

**To prove it**

```bash
curl -s https://friday-zw59.onrender.com/api/self-repair/autonomous
```

`GET` is unauthenticated and read-only on purpose — you should not need a control
key to find out whether the loop has ever run. Expect `status` to move off
`NOT_CONFIGURED` and `missing` to be empty. `running: true` only means the task
is alive; it does not mean a pass succeeded, and should not be read that way.

---

## 3. Phase A2 is labelled done and its evidence was never written

`phaseA2-live-session-evidence-2026-10-01.md` **does not exist in this repo.** The
plan marks A2 "Done 2026-10-01"; the artifact backing that does not.

**To do** — run one live microphone session on the desktop and record what
actually happened: what you said, what FRIDAY transcribed, what tool ran, what
came back, and the wall-clock latency. Save it as
`reports_and_data/phaseA2-live-session-evidence-<date>.md` and commit it.

**To prove it** — the file exists in `main`, and its contents are a real
transcript rather than a summary of intent. A phase whose evidence was never
written is a phase that is not finished, whatever its label says.

---

## 4. Phase B's evidence is missing; the code is not

**This one is different from A2, and the difference matters.**

`build_self_upgrade_context()` **is** wired in and called from
`src/friday/agent/agent.py:302`, where recalled lessons are injected into the
system message behind a quarantine header. The mechanism is real and reachable.

What is missing is `phaseB-evidence-2026-10-01.md`. The phase is labelled COMPLETE
with code behind it and nothing recording that the recall path was ever
exercised.

**To do** — write a lesson, restart, and show the lesson coming back into a live
agent's system message. Record the prompt, the injected block, and what the agent
then did with it.

**To prove it** — the evidence file exists and quotes a real recalled lesson with
the session it came from.

---

## 5. Phase C and Phase D3 were not re-run

- **Phase C** (agents talking) has an evidence file, but the journey is
  cross-repo and has not been re-verified since. Re-run the journey and confirm
  the claimed event IDs still appear. Depends on item 1 — a stale Memora means the
  cloud journey is measuring an old build.
- **Phase D3** (dashboards) is honestly labelled *not started* and owner-blocked.
  It needs dashboard access on the Render account. Nothing has been invented to
  disguise this, which is correct.

---

## 6. The phase evidence table is out of date

`reports_and_data/phaseF-evidence-2026-10-02.md` §4b lists pushed heads but is
missing eleven commits, including every one pushed on 2026-10-02 and 2026-10-03.

**To do** — refresh it after items 1–4, so the record matches `git log`.

---

## What is genuinely finished, and needs nothing from you

Recording this so the list above is not read as "nothing works":

- **Phase F1** — re-measured today, 7/9 LIVE, CI green 9/9. Real and re-runnable.
- **Phase F2** — the loop now has a production caller. Verified by driving it
  end to end against a real gate, not by reading it.
- **Phase E1** — gated pipeline with an owner approval that is single-use and
  fingerprint-bound. Working.
- **Phase E2/E2b** — correctly refuses to promote a strategy on thin evidence.
  That refusal is the feature, not the gap.

---

## The honest summary

Of six phases, **none was fully complete with in-repo proof** when this checklist
was written. Three were real but unrecorded (A2, B, C). One was a demo with no
caller (F2 — now fixed). One was honestly incomplete (D3). One was correct in
refusing (E2).

Items 1 and 2 are the two that unblock the most: a redeploy turns D1 from 2/3 to
3/3 and makes the cloud journey in Phase C measurable against current code, and
five environment variables turn F2 from a proven capability into a running one.

Everything above is owner-only work. None of it is a code change, and none of it
was going to happen by writing more code.