# Task 1 next-run instructions

1. Read `task-1-checkpoint.md` and verify current `main` and feature-branch heads before editing.
2. Continue the FRIDAY task-envelope fix; run its focused regression tests and the existing fleet truthfulness tests.
3. Finish Memora's missing retry-idempotency behavior and add a replay regression test. Preserve its current authentication and namespace-policy behavior.
4. Implement the Inference request/trace/parent correlation contract and add a focused regression test.
5. Run the focused test suites and lint checks; record actual exit codes and test counts only.
6. Open separate PRs when the connector allows it. Do not force-push or auto-merge. If an operation is blocked, record the exact blocker and continue with independent work.
