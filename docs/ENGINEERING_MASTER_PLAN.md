# FRIDAY Engineering Master Plan

**Status:** Active engineering roadmap  
**Repository:** surendra2304/FRIDAY  
**Working rule:** Small, reviewable feature branches; deterministic tests; merge only after required CI passes.

## Mission and definition of done

Make FRIDAY a dependable, secure, maintainable agent—not merely a large codebase. A change is complete when it has a concrete implementation, regression tests, updated docs/configuration where relevant, and CI evidence. Never claim the whole repository is green based on one targeted test or an earlier commit's result.

## Baseline findings

- The repository contains a large Python application and test suite with multiple integrations and optional hardware/live-provider paths.
- A recent main CI run fails during pytest collection because tests/test_consensus_routing_jitter.py imports respx, but respx is absent from the development extras installed by CI.
- The Gemini voice provider's GeminiVoiceOutput.synthesize() currently returns generated zero-valued PCM samples instead of synthesized speech. The interface and docs imply real speech output, so this is a functional gap.
- Verification scripts have historically included non-portable paths and implicit side effects; the separate verification-runner PR addresses those concerns but is based on an older main SHA and must be reconciled against current main before merging.
- Several parallel PRs/automation branches exist. Their changes and CI status must be reviewed individually; do not blindly merge stale or overlapping branches.

## Workstreams and acceptance criteria

### P0 — Restore trustworthy CI

- [x] Add respx to the dev extra used by CI, resolving the currently observed collection error.
- [ ] Re-run CI on the exact proposed commit and confirm lint, syntax checks, full offline pytest, and Docker build all pass.
- [ ] Review any newly exposed failures one by one; do not suppress tests or broaden exclusions just to get a green badge.
- [ ] Keep live provider and physical hardware tests opt-in, but ensure their mocks and contract tests run offline.

### P1 — Secure repository and automation workflows

- [ ] Reconcile the verification-runner PR against the latest main; remove hard-coded machine paths and implicit dependency installation, commit, or push behavior.
- [ ] Make secret scanning fail closed when Git cannot enumerate tracked files; never print secret values.
- [ ] Ensure generated reports/logs have stable locations and do not accidentally capture credentials or user data.
- [ ] Review token handling, subprocess execution, filesystem boundaries, authorization gates, and error sanitization.

### P2 — Make voice capabilities truthful and robust

- [ ] Replace silent PCM generation in the Gemini output adapter with the official Gemini speech-generation API.
- [ ] Keep text-to-speech deterministic in unit tests by injecting/mocking the SDK client; never make normal CI depend on live credentials.
- [ ] Validate empty input, absent credentials, provider errors, empty/malformed audio responses, and successful PCM extraction.
- [ ] Verify sample rate/format assumptions between TTS output and the speaker stream; convert audio only if the format contract requires it.
- [ ] Preserve Live full-duplex streaming as a separate feature from one-shot TTS synthesis.

### P3 — Core architecture and reliability

- [ ] Map package boundaries and import cycles; establish clear contracts for agent, planning, tools, memory, voice, vision, and integrations.
- [ ] Audit async lifecycle management, task cancellation, timeouts, bounded queues, retries/backoff, idempotency, and resource cleanup.
- [ ] Standardize structured errors and sanitized logs; remove swallowed exceptions where they hide failed operations.
- [ ] Add contract tests for external adapters and integration tests for important cross-module workflows.
- [ ] Remove dead code only when references and behavior are verified; no speculative mass deletions.

### P4 — Security, data, and operational readiness

- [ ] Audit secrets/config precedence, authn/authz, tool execution policy, prompt-injection boundaries, and dangerous action confirmation.
- [ ] Verify SQLite persistence, migrations, retention, concurrent access, backup/restore, and corruption handling.
- [ ] Add observability for task lifecycle, provider failures, latency, retries, and cost without leaking prompts or secrets.
- [ ] Validate container build/runtime configuration and document environment variables, health checks, and deployment steps.

### P5 — Capability upgrades

- [ ] Prioritize improvements from demonstrated user workflows rather than line-count targets.
- [ ] Implement bounded asynchronous pipelines with cancellation, backpressure, and deterministic shutdown.
- [ ] Add typed interfaces and schemas around integrations; test degraded/offline states and partial failures.
- [ ] Add performance benchmarks for hot paths and set budgets only after collecting baseline measurements.

## Delivery protocol

1. Inspect current main, open PRs, workflow runs, package metadata, and the exact failing logs.
2. Create a feature/fix branch from the current main SHA.
3. Implement a narrow, production-grade change and add regression tests.
4. Run local checks where a working checkout/runtime is available; otherwise rely on branch CI and state that limitation explicitly.
5. Inspect CI for the exact branch commit, including every job and step.
6. Merge only if the PR is current, conflict-free, and required checks pass. Use a head-SHA guard when supported.
7. Verify the resulting main commit and its push-triggered CI.
8. Update this roadmap with evidence, not assumptions.

## Current execution log

- **2026-10-21:** Merged CI regression fix PR #24 into main at ba9bf79; its preceding branch CI was green. This did not prove future main builds stayed green.
- **2026-10-21:** Identified and opened PR #25 for portable, side-effect-safe verification scripts. Its branch CI later passed, but the PR is stale relative to newer main commits and requires reconciliation before merge.
- **2026-10-21:** Latest inspected main CI failure was pytest collection due to missing respx.
- **2026-10-22:** Added respx>=0.21.0 to the development extra on the current engineering branch. Awaiting branch CI before marking P0 complete.

## Explicit non-goals

- No artificial line-count targets or placeholder implementations.
- No claiming complete repository-wide correctness without full CI and meaningful subsystem audits.
- No merging red/stale PRs merely to clear the queue.
- No automatic force-pushes, destructive resets, or production deployment without explicit authorization.
