# Task 3 — Content automation, software engineering and defensive operations

## Assigned repositories
- VyralX: faceless-video publishing pipeline, sourcing, editing, policy/licensing checks, approvals and upload workflow.
- Forge: autonomous software build/verification/repair engine.
- Sentinel: authorized defensive security assessment and findings workflow.
- Cortex: web/application observability, diagnosis, guarded remediation and operations intelligence.

## Mission
Implement durable product features, not repeated audit reports. Work on all assigned repositories where there is a justified improvement, then validate behavior with tests and builds.

## First-cycle priorities
1. Inspect the actual repositories, open PRs, test suites and unfinished implementation. Choose concrete changes that fit each product's purpose.
2. VyralX: strengthen source metadata and rights/permission provenance, duplicate detection, pipeline state transitions, retry/idempotency, approval gates, render validation and upload-result reconciliation. Only use material the operator is authorized to use; don't build scraping or repost behavior that bypasses access or copyright controls.
3. Forge: improve task planning, isolated execution, test-result capture, failure diagnosis, bounded repair attempts, patch quality gates and durable task state. Do not allow an agent to silently merge risky changes or read secrets.
4. Sentinel: make authorized scope explicit, validate targets against scope, rate-limit scans, preserve audit trails and add regression tests for unsafe target expansion. Do not add offensive payloads or unauthorized exploitation.
5. Cortex: improve health checks, signal quality, alert deduplication, root-cause evidence, guarded remediation plans, rollback criteria and integration tests. No unguarded production destructive changes.
6. Test retries, timeouts, cancellation, malformed responses, partial failures, idempotency and security boundaries.

## Definition of useful progress
- Code changes in implementation plus automated tests and a verified local result.
- Fix regressions introduced by the work; report exact commands and test counts in the checkpoint.
- Prefer observable, recoverable workflows over brittle automation. Make potentially destructive actions gated, auditable and reversible.
- Never commit secrets, bypass licensing/authorization, perform unauthorized scans, or execute production changes without explicit configured controls.
- Do not pad code to hit a number. Cumulative work should naturally produce thousands of meaningful lines across working features, tests and integrations.

## End-of-run obligations
Rewrite this task's persistent checkpoint and next-run prompt before the run ends. Record exact files, behaviors implemented, tests/builds and outcomes, open PRs, blockers and the next concrete coding action. Every next run must continue from that handoff rather than output a report instead of coding.
