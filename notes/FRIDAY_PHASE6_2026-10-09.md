# FRIDAY execution-first audit — phase 6 continuation (2026-10-09)

## Scope and result

- [FACT] Continued the user-facing self-repair/reflex audit with local TestClient requests, a real temporary Git repository and `SelfRepairGate`, a scripted `MockLLMProvider`, local authorization capability issuance, and side-effect-recording fakes. No Gemini/Groq/Mistral/OpenRouter provider, user peer service, external API, browser, device, real message sender, or Windows API was contacted.
- [FACT] Added regression coverage for the self-repair dry-run contract, invalid scopes in the tool/API/CLI, an empty detector include set, the proposal route's malicious target path, and the actual `FridayAgent.process_message` tool-call path.
- [FACT] BUG-004 is reconciled as **partially addressed and still open**; remote capability discovery, peer verification, and a task-polling contract remain unknown because the local repository does not establish them and no peer endpoint was contacted.
- [FACT] The legacy `SelfImprovementWorkflow` remains unsafe to wire. A scoped repository text search found the class implementation and package export, tests/comments, and no in-repo construction outside its module/export. This does not rule out external consumers or dynamic loading.

## Confirmed findings and fixes

### BUG-064 — dry-run previously entered repair handlers

- [FACT] The pre-fix fake-backed regression failed because `SelfRepairTool.execute(dry_run=True)` called `run_once()` once; the fake returned a `RESOLVED` outcome, which the old code would then relabel `DRY_RUN`. The reproduced call count was one, not zero (`tests/test_self_development_tools.py::test_self_repair_dry_run_scans_without_invoking_repair_handlers`).
- [FACT] `SelfRepairTool` now uses only `brain.detector.scan()` for dry-run, sets `acted_on` to zero, and returns `DRY_RUN` detection outcomes without calling `run_once()` or an incident handler (`src/friday/tools/builtin/self_development.py:154-232`; `ReflexBrain.run_once()` invokes handlers at `src/friday/cognition/reflex.py:1492-1524`). A second test verifies the empty-detection reply does not claim a live repair pass (`tests/test_self_development_tools.py::test_self_repair_empty_dry_run_does_not_claim_a_live_repair_pass`).
- [FACT] The user-facing regression drives a `self_repair` tool call through `FridayAgent.process_message` with `MockLLMProvider`, a one-call signed local authorization capability, an incident-detecting fake, and a `run_once()` sentinel that must not fire (`tests/test_self_repair_user_path.py:65-123`). The test observes the tool in the model schema, the authorized tool call, the test-only scan scope, zero repair calls, and the `[DRY_RUN]` result. No real provider was used.
- [INFERENCE] The former exception message could imply no examination or side effect even if an exception escaped after a pass began. The tool now says a complete report is unavailable and partial checks/actions may have completed (`src/friday/tools/builtin/self_development.py:212-224`); it does not claim rollback or absence of effects.

### BUG-065 — invalid scopes could silently widen or change a request

- [FACT] The pre-fix API regression returned HTTP 200 for `scope="typo"` and reached the fake brain instead of rejecting the request (`tests/test_reflex_run_scope_api.py::test_reflex_run_rejects_unknown_scope_without_starting_a_pass`). Pre-fix tool tests also observed invalid mixed scope input reached `run_once()` rather than being refused. The old parsers ignored unknown names and used `None` when no known names remained.
- [FACT] A separately reproduced internal edge case showed `IncidentDetector.scan(include=set())` called all five scanner categories: its old `include or set(IncidentKind)` treated an explicit empty set as all (`tests/test_reflex_brain.py::TestReflexHonesty::test_an_explicit_empty_scope_does_not_widen_to_all_scanners`).
- [FACT] A shared `parse_incident_scope()` now distinguishes an omitted/blank scope (all) from an invalid non-empty scope, rejects unknown or delimiter-only values, and preserves only the requested kinds (`src/friday/cognition/reflex.py:81-112`). The API maps invalid values to HTTP 422 before constructing/running the brain (`src/friday/api/server.py:754-767`); the CLI prints the error and exits 2 (`src/friday/cli/main.py:570-582`); the self-repair tool returns an unsuccessful, refused `ToolResult` without scanning (`src/friday/tools/builtin/self_development.py:169-180`). An explicit empty `include` now selects zero scanners (`src/friday/cognition/reflex.py:498-519`).
- [FACT] Offline tests cover unknown-only, mixed, delimiter-only and valid scopes at HTTP and CLI paths, plus tool-level refusal and detector empty-set behavior (`tests/test_reflex_run_scope_api.py`, `tests/test_reflex_scope_cli.py`, `tests/test_self_development_tools.py`, `tests/test_reflex_brain.py`).

### API proposal path security exercise

- [FACT] Posted a malicious `target_file="../outside.py"` to `/api/self-repair/proposals` using a TestClient, a locally configured `SelfRepairGate(GitRepairApplier(temp_repo))`, and a real temporary Git repository (`tests/test_self_repair_api_path_security.py:22-66`; route implementation `src/friday/api/server.py:637-655`). The route returned HTTP 200 with an explicit `REFUSED` receipt containing `INVALID_TARGET_PATH` and a `BLOCKED` record. The repo HEAD remained the initial commit, `git status --porcelain` was empty, and no sibling `outside.py` appeared.
- [FACT] HTTP 200 is the current receipt-envelope contract for a gate refusal, not a claim that the proposal was accepted. The regression asserts the explicit receipt and unchanged repository rather than inferring safety from status code alone.

## Verification

- [FACT] Focused affected path/security/delegation batch: **180 passed in 17.29s**. It included self-development tools, the `FridayAgent` user path, the proposal API route, reflex API/CLI scope handling, the reflex brain, the repair gate, and typed-mesh task dispatch.
- [FACT] Final portable suite: **2,372 passed, 6 skipped, 23 deselected in 307.67s**. Command: `PYTHONPATH=src .venv/bin/python -m pytest -q -m "not live and not hardware and not windows"`. The final runtime output is in ignored `notes/full_test_run_2026-10-09_v4.log`; this markdown record preserves the result.
- [FACT] Full-tree Ruff passed (`.venv/bin/python -m ruff check src tests`); full-source Mypy passed with no issues in **427 source files** (`.venv/bin/python -m mypy src/friday`); `git diff --check HEAD` passed.
- [FACT] The first run in the recreated virtual environment had one environment failure: `test_browser_use_executor_availability` expected the optional Playwright package. Playwright's Python package was installed from PyPI without downloading a browser; `pip check` was clean and the isolated availability test passed. The final suite v4 then passed. No browser was launched.
- [FACT] A focused v1 suite log and v2 full-suite result preceded the last scope changes; they are superseded by the final v4 result above.
- [FACT] `live`, `hardware`, and `windows` marked tests were excluded. Real Windows UI/device behavior and external peer/provider compatibility remain unverified.

## BUG-004 and other open boundaries

- [FACT] BUG-004's local user path uses a typed task mesh, receipt validation, and preserves HTTP 202 pending results/remote IDs; local tests use `ContractTransport`, not a live peer. `docs/FRIDAY_KNOWN_ISSUES.md:20` remains open for peer capability discovery, task polling, and live verification.
- [INFERENCE] Local contract tests prove envelope creation, route selection, and local result classification only. They do not prove that deployed peers accept the schema or expose a polling endpoint.
- [FACT] BUG-003r remains open: the registered `self_develop` tool uses the gated resolver; the exported legacy workflow still writes generated code before permission and is not connected to the supported tool path (`docs/FRIDAY_KNOWN_ISSUES.md:28`; sampled implementation in `src/friday/workflows/self_improve_workflow.py:162-240`). Do not wire it without replacing its authorization/write/test/Git gates.
- [FACT] BUG-007 remains an owner configuration decision; BUG-016 remains an artifact-retention decision. The Linux Qt/OpenGL and Windows runtime boundaries described in prior notes remain unresolved here.

## Read-depth record

- **Deeply read:** the complete new tests `tests/test_self_repair_user_path.py` (123 lines), `tests/test_self_repair_api_path_security.py` (66 lines), `tests/test_reflex_scope_cli.py` (60 lines), and `tests/test_reflex_run_scope_api.py` (60 lines); the new regression section of `tests/test_reflex_brain.py`; `AGENT_PROGRESS.md`; and the active worklog's BUG-004 and latest-phase sections.
- **Sampled, not fully read:** `src/friday/tools/builtin/self_development.py` (292 lines; current `SelfRepairTool` and rendering paths only); `src/friday/cognition/reflex.py` (1,603 lines; scope parser, aggregate scanner, and run loop only); `src/friday/api/server.py` (1,642 lines; proposal and reflex routes only); `src/friday/cli/main.py` (1,201 lines; reflex CLI branch only); `tests/test_self_development_tools.py` (361 lines; relevant self-repair cases); `tests/test_reflex_brain.py` (536 lines; relevant detector/reflex tests); and `src/friday/workflows/self_improve_workflow.py` (relevant lines only). The whole large source/test files were not reviewed end-to-end.
- **Skipped:** remaining functions in those large files, external peer/service code not present in the checkout, live provider behavior, Windows host/device behavior, and unrelated repository paths not needed for this phase. This phase note is not a claim of a complete repository audit.

## State at checkpoint

- [FACT] The evidence-bounded final analysis is saved at `/home/user/REPO_ANALYSIS.md` and mirrored at `notes/REPO_ANALYSIS.md`; the report explicitly retains open/unknown items and read-depth limits.
- [FACT] The later user instruction authorizes committing completed checklist work and pushing only this branch if a remote is configured; the earlier worklog line saying no commit/push was authorized is superseded. Final diff/status/remote check is still required before commit/push.
- [FACT] Active-work duration is unmeasured; no hours claim is made.
