# FRIDAY Audit Progress

**Current step:** 7 — current phase evidence and evidence-bounded repository analysis are delivered. Audit commit `5ec11a8` is pushed to the fixed branch; complete the small final documentation update on that same branch, verify the final clean status, and leave broader audit scope explicitly open.

**Recovery baseline (2026-10-08):** `AGENT_PROGRESS.md` was absent. Rebuilt this checklist from the active task, session checkpoint, worktree, and test-run records. Branch: `arena/f8c95cce-friday`; base commit: `f2d427c`. The worktree already contained a broad audit patchset before this continuation; do not reset, revert, or discard it. Initial recovery status showed 111 changed/untracked paths and 7,319 insertions / 1,887 deletions. Latest full portable run from this continuation: **2,372 passed, 6 skipped, 23 deselected in 307.67s** (`notes/full_test_run_2026-10-09_v4.log`, ignored runtime log; summary is preserved in the phase note/worklog). Full-tree Ruff passed, Mypy reported no issues in 427 source files, and `git diff --check HEAD` passed after the latest source/test changes.

## Checklist

- [x] Resume and preserve the pre-existing audit patchset; confirm branch, base history, worktree status, and absence of this progress file.
- [x] BUG-056: route exact Gmail inbox-opening commands to Gmail; controller/API regressions were included in the v9 suite.
- [x] BUG-057: report WhatsApp page-open as unconfirmed, not dispatched/delivered; API distinguishes pending (202) from open failure (502); covered in v9.
- [x] Record v9 full portable-suite result and passing Ruff/Mypy gates in `notes/FRIDAY_ACTIVE_WORKLOG.md`.
- [x] Add offline API peer-task coverage that forbids fleet-client calls; its focused test passed before this continuation.
- [x] BUG-058: keep `compose`/`draft`/`write`/`new email` intents on the Gmail draft-only route; prove the SMTP boundary is not crossed and cover the user-facing API route. Offline tests pin SMTP exclusion, approved draft open, denied authorization (403), failed browser open (502), and draft-only phrasing variants.
- [x] BUG-059: prevent Gmail Ctrl+Enter worker startup when opening the requested compose URL fails, so a stale Gmail window cannot receive the keypress. The worker now requires a successful `open_url`; offline window/driver regression passes.
- [x] Focused Gmail/controller/API/authorization suite after current edits: **135 passed, 3 deselected**.
- [x] Full-tree Ruff and Mypy after BUG-058/059, before the later BUG-060 parser edit: Ruff passed; Mypy reported no issues in 426 source files; `git diff --check HEAD` passed.
- [x] Full portable pytest suite v11 before the later BUG-060 parser edit: **2,301 passed, 6 skipped, 23 deselected**; `notes/full_test_run_2026-10-08_v11.log`.
- [x] Update `docs/FRIDAY_KNOWN_ISSUES.md` and `notes/FRIDAY_ACTIVE_WORKLOG.md` with established BUG-058/059 findings and verification evidence.
- [x] BUG-060: resolve Gmail named recipients correctly, keep subject-only text from becoming a contact, and refuse unresolved names without opening a blank draft. Context-specific parser and controller/API regressions pass.
- [x] Run the broader Gmail/controller/API/authorization/WhatsApp/fast-path batch after BUG-060: **140 passed, 3 deselected**.
- [x] Rerun full-tree Ruff and Mypy after BUG-060; Ruff passed and Mypy reported no issues in 426 source files.
- [x] Rerun portable suite after BUG-060: **2,306 passed, 6 skipped, 23 deselected**; `notes/full_test_run_2026-10-08_v12.log`.
- [x] Update BUG-060 notes with reproduction, code/test evidence, and exact post-fix full-suite/static results.
- [x] BUG-006: live app-router inspection found no duplicate `(path, method)` pairs; global uniqueness and telemetry regressions pass (**2 passed**); issue register updated.
- [x] BUG-013: implement shared fleet-client shutdown close/release and connect it to API lifespan. Both local lifecycle regressions failed before the fix and now pass; no HTTP request was made.
- [x] Rerun affected API/fleet/Gmail/controller/authorization/WhatsApp/fast-path suite after BUG-013: **161 passed, 3 deselected**.
- [x] Rerun full-tree Ruff/Mypy and diff check after BUG-013: Ruff passed, Mypy no issues in 426 files, `git diff --check HEAD` passed.
- [x] Rerun portable pytest after BUG-013: **2,309 passed, 6 skipped, 23 deselected**; `notes/full_test_run_2026-10-08_v13.log`.
- [x] BUG-037: reproduce the Linux `launch_app("camera")` false-success before the fix; add offline regressions for fixed process launches, Chrome argv launch, settings, screenshot fallback, sleep, and monitor browser behavior; route them through verified effects.
- [x] BUG-061: preserve recognized application-launch failures as handled directives so `/api/command` returns HTTP 502 instead of passing the request to the general agent; keep unknown app names on the existing deterministic generic-launch/refusal route.
- [x] Reproduce BUG-061 pre-fix: the local `open camera` controller regression failed because `handle_directive` returned `handled=False`; post-fix controller/API tests assert `success: false`, HTTP 502, and no agent call.
- [x] FridayAgent/fast-path regression drives `open camera` with a failing local effect and a provider sentinel; the directive returns `success: false` without calling the LLM.
- [x] Focused effects/device/API/controller/authorization/WhatsApp/fast-path/fleet batch after BUG-037/061: **197 passed, 3 deselected**.
- [x] Full-tree Ruff, full-source Mypy, and `git diff --check HEAD` after code/test/doc edits: Ruff passed, Mypy no issues in 426 source files, diff check passed.
- [x] Portable full suite v15: **2,328 passed, 6 skipped, 23 deselected** in 289.47 s; `notes/full_test_run_2026-10-08_v15.log`.
- [x] Reconcile the BUG-004 task-dispatch candidate using offline stand-ins: reproduce the user-facing status-query path, route execution directives through the typed task mesh, require receipt-backed verification for success, and preserve pending task IDs/status. BUG-004 remains **partially addressed/open** because no remote capability-discovery or polling contract was found and no peer endpoint was contacted; see the 2026-10-08 BUG-004 worklog section and its explicit blocked/unknown boundary.
- [x] BUG-064: reproduce and fix the self-repair dry-run that entered `run_once()` before rewriting statuses; use a side-effect-recording fake and a scripted-provider `FridayAgent.process_message` path to prove the repair handler is never entered.
- [x] BUG-065: reproduce and fix silent scope widening across `self_repair`, `/api/reflex/run`, `friday --reflex-run`, and `IncidentDetector.scan(include=set())`; share a fail-closed scope parser and keep valid scopes narrow.
- [x] Exercise `/api/self-repair/proposals` over a local TestClient using a real temporary Git repo and locally configured `SelfRepairGate`; malicious `../outside.py` returns an explicit `INVALID_TARGET_PATH` refusal, leaves the temp repo at the same HEAD with a clean status, and writes nothing outside it.
- [x] Re-run focused user-path/security/repair/delegation tests: **180 passed in 17.29s**; portable full suite v4: **2,372 passed, 6 skipped, 23 deselected in 307.67s**.
- [x] Full-tree Ruff, full-source Mypy (427 source files), and `git diff --check HEAD` pass after the latest source/test changes.
- [x] Continue the execution-first audit through additional user-facing paths in this continuation: scripted `FridayAgent` self-repair dry-run, a local gated malicious-proposal HTTP request, and reflex API/CLI scope requests. The wider repository is not claimed fully audited; preserve the explicit skipped/sample boundaries.
- [x] Preserve per-phase `[FACT]` / `[INFERENCE]` / `[HYPOTHESIS]`, `path:line`, and read-depth evidence in `notes/FRIDAY_PHASE6_2026-10-09.md` and `notes/FRIDAY_ACTIVE_WORKLOG.md`; create `/home/user/REPO_ANALYSIS.md` and mirror it at `notes/REPO_ANALYSIS.md`. Large `windows_friday.py`, `api/server.py`, `cli/main.py`, and `reflex.py` remain sampled, not fully read.
- [x] Verified the fixed branch and configured `origin`; committed the audit patch as `5ec11a8` and pushed only `arena/f8c95cce-friday`. This final progress/worklog status is being committed and pushed as a small follow-up on the same branch; verify clean status after that push.
- [x] Preserve the open audit boundary and precise next-action checkpoint; active-work duration remains unmeasured (not invented), and touched/created artifacts are listed in the final response.

## Operating Constraints

- Repository is authoritative; preserve source and prior changes non-destructively.
- Use local/offline stand-ins; no Gemini/Groq/Mistral/OpenRouter egress, Windows APIs, user peer services, live messaging, or unmocked device actions.
- Do not claim that tests alone prove real-world operation; state what stand-ins cover and what remains unknown.
- Do not pad code or claim all possible bugs are fixed. Never idle to satisfy the active-hours target.
- `REPO_ANALYSIS.md` is now an evidence-bounded synthesis of reviewed paths; it must not be described as an exhaustive file-by-file audit, and later phases should extend it only with new evidence.
