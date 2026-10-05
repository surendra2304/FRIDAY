# FRIDAY Bug & Risk Register

**Last rewritten:** 2026-10-05, from the Phase 0–2 truth audit
(`docs/reports/phase0-2-truth-audit-2026-10-05.md`) and the Phase 5 proof report
(`docs/reports/phase5-autonomy-proof-2026-10-05.md`).

This file used to hold three stale entries (two Low, one Medium) and none of the
findings from the audit — that staleness was itself BUG-015. Every row below was
observed by a command that was actually run; "FIXED" means a regression test now
pins it and the full suite is green.

Severity: **CRITICAL** = can destroy the owner's work or lie about safety;
**HIGH** = a claim the system makes that the system cannot support;
**MEDIUM** = real defect with a workaround; **LOW** = hygiene.

---

## Open

| ID | Sev | Component | File | Finding | Status | Next step |
|---|---|---|---|---|---|---|
| BUG-004 | HIGH | Ecosystem / delegation | `ecosystem/fleet_client.py` (`ask_*`), `autonomous/controller.py` | "Delegating work to the 8 agents" is a health probe: the `ask_*` methods hit read-only health/status endpoints, and task completion is never verified. A health payload is formatted as an agent response. | **OPEN** | A typed peer task channel: `TaskEnvelope` in, async receipt + polling `TaskResult` out, per-peer capability discovery, completion verifier. Report `SUCCESS` only on a completion receipt. |
| BUG-006 | MEDIUM | API | `api/server.py` | Dead duplicate route definitions (two handlers for the same path; the second never runs). | **OPEN** | Confirm which one is live with a real request, delete the dead one, and pin the surviving contract with a test. |
| BUG-007 | MEDIUM | Config | inference defaults | Inference defaults are not the values the deployment actually needs; a fresh install silently runs a degraded configuration. | **OPEN** | Decide the real defaults with the owner, set them in one place, pin with a test. |
| BUG-008 | MEDIUM | Autonomy | `core/config.py`, `autonomous/` | Two sources of truth for `autonomous_mode`; they can disagree about whether FRIDAY may act. | **OPEN** | One authority for the flag, the other reads it; a test that the two agree. |
| BUG-009 | MEDIUM | Packaging | `pyproject.toml` | Packaging does not install the package in a way a clean machine can run. | **OPEN** | Build a wheel, install it into a fresh venv, and run the CLI from outside the checkout. |
| BUG-012 | LOW | API | `api/server.py:638`, `:1022` | Failure responses return **HTTP 200** with `success:false`; a client cannot distinguish refusal from completion without parsing the body. | **OPEN** | Return a non-200 status for refusals; keep the body shape. |
| BUG-013 | LOW | Ecosystem | `ecosystem/fleet_client.py:75` | `_shared_client` (lazy `httpx.AsyncClient`) is never closed; sockets leak across reloads. | **OPEN** | Close it on shutdown; assert `is_closed` in a test. |
| BUG-016 | LOW | Repository | `reports_and_data/` (75 files) | Committed run artifacts, referenced by nothing, drifting silently. | **OPEN** | Move to external storage or delete; keep the repo to code and docs. |
| BUG-003r | MEDIUM | Self-improvement | `workflows/self_improve_workflow.py` | The registered tools `self_develop`/`self_repair` are real and in the catalogue, but `SelfImprovementWorkflow` itself is not wired into any live tool path, and `tests/test_self_improve_workflow_phase31.py` exercises mocks rather than the real pipeline. | **OPEN (remainder)** | Either register the workflow behind a real tool with honest evidence, or delete the workflow and keep the tools. |
| BUG-014r | LOW | Ecosystem | `ecosystem/fleet_client.py` | The false `consensus_reached: True` is gone, but the fast lane still caps `max_tokens: 60`, which is too small for anything but a status quip. | **OPEN (owner decision)** | Raising it changes cloud spend; ask before changing. |
| BUG-015 | LOW | Docs | this file | The register was stale and recorded none of the audit's findings. | **FIXED (2026-10-05)** | Keep this file updated when findings are fixed. |

## Fixed, with the regression test that pins it

| ID | Sev | Finding | Fixed by | Pinned by |
|---|---|---|---|---|
| BUG-001 | CRITICAL | Unbounded self-edit path could write and commit without a gate | gate + mandate work (`70ddc7a`) | `tests/test_self_repair_gate.py`, `tests/test_autonomy_mandate.py` |
| BUG-002 | HIGH | Autonomy was unreachable: no live API/CLI surface for mandate or repair state | `4bf0c9d` | `tests/test_cognition_surface.py`, `tests/test_repair_trigger.py` |
| BUG-003 | HIGH | The system prompt ordered a tool call (`SelfImprovementWorkflow`) that did not exist, so "add a capability" produced a phantom call | `32d284f` (`SelfDevelopTool`, `SelfRepairTool` registered) | `tests/test_capability_synthesis.py` |
| BUG-005 | HIGH | Evidence inversion: 8 unreachable peers reported as 8 observed responses; connection errors called `DEGRADED` | `4b451fa` | `tests/test_peer_evidence_inversion.py` |
| BUG-010 | HIGH | The loop's repeat-guard notices were persisted as long-term memory and recalled into unrelated conversations | `b137065` | `tests/test_memory_write_filter.py` |
| BUG-011 | HIGH | Approval and mandate issuance were guarded by a deny-list, so any unlisted name (including a future agent) could approve a repair | `b137065` | `tests/test_owner_identity_is_positive.py` |
| BUG-005b | HIGH | A real unattended repair committed the whole dirty tree (`gate_state.json`, a `.pyc`) with the fix | `07cfc33` | `tests/test_repair_commit_scope.py` |
| BUG-005c | HIGH | A transport that never answered hung a dispatch forever | `07cfc33` | `tests/test_extreme_pressure.py` |
| BUG-005d | MEDIUM | The circuit breaker counted one failure per dispatch, not per attempt, so it opened far later than configured | `07cfc33` | `tests/test_extreme_pressure.py` |
| BUG-014 | LOW | `ask_inference` claimed `consensus_reached: True` on any HTTP 200, from a single model | `91de283` | `tests/test_peer_evidence_inversion.py` |

## Known limitations that are not defects

- **No egress from the development sandbox.** Live peer calls and cloud LLM
  providers are **CONFIGURED-BUT-UNVERIFIED** here; the contracts and the
  in-process harness are real. See the Phase 5 report's REAL vs
  CONFIGURED-BUT-UNVERIFIED table.
- **`pytest --timeout` is unavailable** (no `pytest-timeout`), so per-test bounds
  come from the code under test (`RepairRunner.timeout`,
  `IncidentDetector.test_timeout`) rather than from pytest.
- **Windows-marked tests fail on Linux by design** and are deselected with
  `-m "not windows"`.
- **`run_forever()` sleeps before its first pass** — deliberate, so a restart is
  not a repair storm; measured at a 60 s interval in the Phase 5 report.
