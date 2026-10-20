# Task 1 — Core intelligence and memory

## Assigned repositories
- FRIDAY: master assistant, multimodal gateway, orchestration, tool routing and agent integration.
- Inference: provider/model routing, inference API, fallback and runtime reliability.
- Memora: persistent memory, storage, retrieval, scopes and migration safety.

## Mission
Continuously implement production-quality code across all three assigned repositories. Prioritize tested user-facing capability and reliability improvements, not documentation-only or status-report-only work.

## First-cycle priorities
1. Inspect repository state, current main heads, open PRs and test setup. In FRIDAY, inspect open PR #15 and avoid duplicating its unmerged allocator changes; improve independent code paths or tests unless a clear fix is needed to unblock integration.
2. Trace FRIDAY to Inference dispatch: request contracts, authentication boundaries, provider routing, timeouts, retries, streaming and typed error propagation. Implement the highest-impact missing behavior with tests.
3. In Memora, protect the memory model: private memories per agent, shared memories for agents explicitly authorized to share, and universal memories available to all designated agents. Test cross-agent data isolation and persistence.
4. Validate backward compatibility, safe defaults, configuration errors, missing providers, malformed input, cancellation and failure recovery.

## Definition of useful progress
- Code changes in implementation and automated tests.
- Run existing focused tests, lint and build checks. Fix regressions introduced by the work.
- Where integration tests require unavailable infrastructure, add deterministic mocked tests and document the precise limitation in the checkpoint.
- Preserve SQLite compatibility where currently supported while improving PostgreSQL paths; never perform an irreversible migration or delete user data.
- Do not add secrets, hard-coded API keys, mock success responses in production code, or unbounded retries.
- Do not pad code to meet a line target. Build the needed feature fully; cumulative work should naturally produce thousands of meaningful implementation and test lines over time.

## End-of-run obligations
The coding worker must rewrite its checkpoint and its next-run prompt with exact files, implementation outcomes, commands and pass/fail counts, unresolved failure causes, and the next concrete coding action. The next cycle must continue from those instructions rather than repeat the same reconnaissance.
