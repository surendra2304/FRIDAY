# FRIDAY Repository Analysis — execution-first audit

**As of:** 2026-10-09

**Repository:** `surendra2304/FRIDAY`

**Audit branch:** `arena/f8c95cce-friday`

**Source-of-truth boundary:** the checked-out repository and the local test harnesses only. No deployment, customer system, live provider, or peer service was assumed.

## Executive summary

- [FACT] The repository contains several distinct user-facing execution surfaces—tool calls, `/api/command`, cognition/reflex HTTP endpoints, CLI commands, and desktop/directive handlers. A claim is only as strong as the specific path that produces it; a passing isolated unit test is not evidence that the user-facing route reaches that behavior. The live tool registry registers `self_develop` and `self_repair` (`src/friday/agent/mixins/tools.py:237-243`), and the registered self-development tool is the documented supported path (`README.md:40`).
- [FACT] This audit's execution-first fixes address truthful outcomes, authorization boundaries, path confinement, task delegation, and tested integrations. The known-issues register records the reproduced defects and their exact regressions; it deliberately retains unresolved rows (`docs/FRIDAY_KNOWN_ISSUES.md:16-59`).
- [FACT] The final portable suite run passed **2,372 tests**, with **6 skipped** and **23 deselected**, in **307.67 seconds**. The run excludes `live`, `hardware`, and `windows` tests. Full-tree Ruff passed; Mypy reported no issues in 427 source files; `git diff --check HEAD` passed. The command and phase-specific coverage are recorded in `notes/FRIDAY_PHASE6_2026-10-09.md` and `notes/FRIDAY_ACTIVE_WORKLOG.md:186-216`.
- [INFERENCE] These results provide good regression evidence for the covered local paths, but not proof that all defects are fixed, that all source files were reviewed, or that a deployed service or real Windows device behaves identically. Large files and untested deployment boundaries are called out below.

## What was exercised through user-facing paths

### Self-development and self-repair

- [FACT] The `self_develop` tool uses the capability resolver/synthesizer and can be driven with a scripted offline provider; its test stops at the owner-authority gate rather than claiming an installation occurred (`src/friday/tools/builtin/self_development.py:31-103`; `tests/test_generated_tool_path_security.py::test_self_develop_user_path_uses_module_stem_and_stays_offline`; `docs/FRIDAY_KNOWN_ISSUES.md:28`).
- [FACT] Generated capability targets are confined to direct Python modules under `src/friday/tools/builtin`, and the repair gate validates repository-relative targets at proposal and write boundaries (`src/friday/cognition/tool_paths.py:1-84`; `src/friday/cognition/installation.py:170-183`; `src/friday/autonomous/self_repair.py:110-143,718,1028-1036,1460-1468`; `docs/FRIDAY_KNOWN_ISSUES.md:57`).
- [FACT] **BUG-064 fixed:** `SelfRepairTool.execute(dry_run=True)` previously called `run_once()`—which scans and invokes handlers—then rewrote outcome labels. It now calls the detector's scan-only path, sets `acted_on=0`, and reports detections without invoking handlers (`src/friday/tools/builtin/self_development.py:154-232`; the action loop is `src/friday/cognition/reflex.py:1492-1524`). A fake-backed failure reproduced a call to `run_once()` before the fix (`tests/test_self_development_tools.py::test_self_repair_dry_run_scans_without_invoking_repair_handlers`).
- [FACT] The self-repair dry-run was also driven through `FridayAgent.process_message` with a scripted `MockLLMProvider`, a one-call signed local authorization capability, and a fake detector/repair sentinel. The actual registered tool was visible to the model, authorization was exercised, detection ran, and the handler sentinel remained untouched (`tests/test_self_repair_user_path.py:65-123`). No live model provider was used.
- [FACT] The `/api/self-repair/proposals` route was tested with a real temporary Git repository and a locally configured `SelfRepairGate`. `target_file="../outside.py"` returned an explicit `REFUSED` receipt with `INVALID_TARGET_PATH`; the record was `BLOCKED`, the temporary repository stayed on its original HEAD with a clean status, and no outside file was created (`src/friday/api/server.py:637-655`; `tests/test_self_repair_api_path_security.py:22-66`). The route uses HTTP 200 for its receipt envelope even on a gate refusal; the body, not the status alone, determines acceptance.

### Reflex scope handling

- [FACT] **BUG-065 fixed:** one shared `parse_incident_scope` distinguishes omitted/blank scope (all) from invalid non-empty scope, rejects unknown and delimiter-only values, and keeps valid scope selections narrow (`src/friday/cognition/reflex.py:81-112`). The HTTP route maps invalid input to 422 before starting a pass (`src/friday/api/server.py:754-767`); the CLI prints an error and exits 2 (`src/friday/cli/main.py:570-582`); the self-repair tool returns an unsuccessful refusal without scanning (`src/friday/tools/builtin/self_development.py:169-180`).
- [FACT] Before the fix, `/api/reflex/run` returned 200 for an unknown scope and invoked the fake brain. A separate test-first reproduction showed `IncidentDetector.scan(include=set())` running all five scanner categories because the old implementation treated an empty set as false/all. The detector now treats only `None` as all (`src/friday/cognition/reflex.py:498-519`). API and CLI tests cover unknown-only, mixed, delimiter-only, and valid scope requests (`tests/test_reflex_run_scope_api.py`, `tests/test_reflex_scope_cli.py`); the empty-set test is `tests/test_reflex_brain.py::TestReflexHonesty::test_an_explicit_empty_scope_does_not_widen_to_all_scanners`.

### Delegation and task status

- [FACT] **BUG-004 is partially addressed, not closed.** The user-facing controller now sends execution directives through the typed mesh rather than read-only `ask_*` health/status calls; success requires matching verification evidence, and HTTP 202 preserves pending state and the remote task ID (`src/friday/autonomous/controller.py:202-310`; `src/friday/cognition/mesh.py:432-510,867-881`; `src/friday/api/server.py:953-973`). Local tests use `ContractTransport` and local responses (`tests/test_autonomous_task_dispatch.py`, `tests/test_fleet_task_truthfulness.py`, `tests/test_mesh.py`).
- [INFERENCE] The local contract proves request construction, route selection, result classification, and receipt checking. It does **not** prove that deployed peers accept this schema, expose capability discovery, or provide a poll/status endpoint. No peer was contacted, so live compatibility remains unknown (`docs/FRIDAY_KNOWN_ISSUES.md:20`; `notes/FRIDAY_ACTIVE_WORKLOG.md`, BUG-004 section).

### API, authorization, integrations, and system effects

- [FACT] The API now distinguishes refusal and failure from success across the command path; documented statuses include 403 for authorization/security refusal, 422 for invalid/missing input, 502 for unconfirmed direct effects or adapter failure, and 500 for marked execution exceptions (`src/friday/api/server.py:273-322,944-973`; `docs/FRIDAY_KNOWN_ISSUES.md:25,44`).
- [FACT] The audit also added regressions for duplicate route registration, Android status/action truthfulness, verified desktop process/browser effects, WhatsApp's unconfirmed asynchronous dispatch, Gmail draft-versus-send routing, and failed-launch fallthrough (`docs/FRIDAY_KNOWN_ISSUES.md:21,31,44-53`). Each row names its tests and the associated limitations.
- [FACT] Local service doubles exercise Nexus/FORGE/task routing without contacting user peer services (`tests/mock_nexus_api.py`, `tests/mock_forge_api.py`, `tests/test_autonomous_task_dispatch.py`). These remain local contract tests, not proof of remote uptime or deployed compatibility.

## Open, blocked, or owner-dependent items

- [FACT] **BUG-004:** remote capability discovery, verified deployed-peer behavior, and task polling remain unresolved; no peer endpoint was contacted (`docs/FRIDAY_KNOWN_ISSUES.md:20`).
- [FACT] **BUG-003r:** the registered `self_develop` tool is the supported gated path. `SelfImprovementWorkflow` is separately exported, not found instantiated in the in-repo source search, and its sampled implementation writes generated code before asking authorization. It must not be wired into a live path without redesigning and validating its gate (`src/friday/workflows/self_improve_workflow.py:162-240`; `src/friday/workflows/__init__.py:7-15`; `README.md:40,72`; `docs/FRIDAY_KNOWN_ISSUES.md:28`). External consumers and dynamic imports cannot be ruled out by text search.
- [FACT] **BUG-007:** `Settings` defaults `llm_provider` to `gemini`, while `.env.example` recommends `chain`; keyless direct-Gemini construction can use the configured Inference gateway. The repository does not establish the owner's intended deployment default, so no preference was invented and no provider was contacted (`src/friday/core/config.py:194`; `.env.example:12-20`; `src/friday/llm/factory.py:60-72`; `docs/FRIDAY_KNOWN_ISSUES.md:22`).
- [FACT] **BUG-016:** 75 tracked files (564 KiB) remain in `reports_and_data/`. Research scripts write there, but the scoped search did not establish a consumer of the existing artifacts; retention/ownership is an owner decision. Nothing was moved or deleted (`docs/FRIDAY_KNOWN_ISSUES.md:27`).
- [FACT] Desktop packaging is split into optional extras; the clean Linux desktop extra installed, but UI startup is blocked by missing host `libGL.so.1`. `voice-bio` native dependencies and real Windows GUI behavior remain unverified (`pyproject.toml:40-57`; `docs/FRIDAY_INTEGRATION.md`; `docs/FRIDAY_KNOWN_ISSUES.md:24`).
- [FACT] The final run excludes live, hardware, and Windows markers. Real Windows URI/keyboard/display behavior, physical device actions, live messaging, and external provider/peer responses were not exercised (`pyproject.toml:82-98`; `notes/FRIDAY_PHASE6_2026-10-09.md`).

## Verification record

| Gate | Final result | Boundary |
|---|---|---|
| Focused user-path/security/repair/delegation batch | **180 passed, 17.29s** | Local fakes, temporary Git repo, TestClient, scripted provider |
| Portable full suite | **2,372 passed, 6 skipped, 23 deselected; 307.67s** | Excludes `live`, `hardware`, `windows` |
| Ruff | Passed: `.venv/bin/python -m ruff check src tests` | Source and tests |
| Mypy | Passed: no issues in **427 source files** | `src/friday` |
| Whitespace/diff check | Passed: `git diff --check HEAD` | Current worktree diff |
| Packaging / environment | `pip check` clean after installing the optional Playwright Python package | No browser installed/launched; Linux Qt host dependency still missing |

[FACT] The ignored runtime log `notes/full_test_run_2026-10-09_v4.log` is not committed; the exact final command/result and evidence are preserved in `notes/FRIDAY_PHASE6_2026-10-09.md` and `notes/FRIDAY_ACTIVE_WORKLOG.md`.

## Review-depth limits

- **Deeply read:** the complete new regression files `tests/test_self_repair_user_path.py`, `tests/test_self_repair_api_path_security.py`, `tests/test_reflex_scope_cli.py`, and `tests/test_reflex_run_scope_api.py`; the new detector regression; the relevant self-repair and scope paths; `AGENT_PROGRESS.md`; the active worklog; and the known-issues register.
- **Sampled:** `src/friday/cognition/reflex.py` (1,603 lines), `src/friday/api/server.py` (1,642), `src/friday/cli/main.py` (1,201), and `tests/test_reflex_brain.py` (536). Only scope parsing, the aggregate scanner, reflex run loop, proposal route, reflex route, and CLI reflex command were inspected. `src/friday/tools/builtin/self_development.py` (292) and `tests/test_self_development_tools.py` (361) were also read around relevant self-repair code, not as an exhaustive audit of every branch.
- [HYPOTHESIS] Additional defects may remain in the unreviewed portions of these files and elsewhere in the repository. No claim of complete file-by-file review or complete bug elimination is made.

## Changes from the 2026-10-09 continuation

- Source: `src/friday/cognition/reflex.py`, `src/friday/tools/builtin/self_development.py`, `src/friday/api/server.py`, `src/friday/cli/main.py`.
- Tests: `tests/test_self_development_tools.py`, `tests/test_reflex_brain.py`; new `tests/test_self_repair_user_path.py`, `tests/test_self_repair_api_path_security.py`, `tests/test_reflex_run_scope_api.py`, `tests/test_reflex_scope_cli.py`.
- Evidence/checklist: `docs/FRIDAY_KNOWN_ISSUES.md`, `AGENT_PROGRESS.md`, `notes/FRIDAY_ACTIVE_WORKLOG.md`, `notes/FRIDAY_PHASE6_2026-10-09.md`.
- [FACT] The broader audit patchset on this branch predates this continuation. Consult `git status`/the final commit for the complete touched-path inventory; do not infer that the short phase-specific list covers all prior audit work.
