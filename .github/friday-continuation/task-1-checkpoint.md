# FRIDAY Universe — Task 1 checkpoint

Updated: 2026-10-21 11:00 IST

## Status

Partial engineering changes are committed to remote feature branches. No implementation PR was opened because the GitHub pull-request creation call was blocked by the tool safety layer. No code was merged. No tests were executed in this run.

## FRIDAY

- Branch: `fix/task1-task-contract-20261021`
- Commit: `c0ba21ee2a44c103dfccb5b9f3a21d43680520fe`
- Changed `src/friday/core/task_envelope.py`:
  - Materializes a generated `task_id` inside the before-validator before deriving the default `idempotency_key`.
  - Defaults the key to `idem_{task_id}`, fixing the previous mismatch where the key could be generated from a separate random value.
  - Bounds `task_id` to 64 characters to align with Memora's persisted task-id column.
  - Adds input length validation for trace, parent-task, request, and idempotency identifiers.
- Added `tests/test_task_envelope_identity.py` with five regression tests.
- Validation: source and test files were fetched back from GitHub and the commit diff was inspected. Pytest/lint were not run. Commit status has no checks because no PR was opened.

## Memora

- Branch: `fix/task1-task-contract-20261021-r2`
- Latest implementation commit: `901b3933cd7309edb2eb94fa14cfc4150efcf005`
- Earlier branch commits: `48df4bfb3dc047d2823f4a33907eeca9e6a40d3e` and `efb8193277f632f70e6b46e4d9440e42192e388c`.
- Changed `apps/api/routers/v1_task.py`:
  - Bounds `task_id` to 64 characters to match `MemoryRecord.task_id` storage.
  - Accepts `request_id` and `parent_task_id` and returns trace/request/parent correlation fields.
- Added `tests/test_task_envelope_validation.py` to reject task IDs longer than the storage contract.
- Important unresolved defect: the endpoint still does not pass `task_id` and an idempotency key to `MemoryWriteService.execute_pipeline`. An attempted write for that change was blocked by the tool safety layer, so do not claim retry-safe task writes are fixed.
- Validation: GitHub commit diffs inspected; tests not run.

## Inference

- Branch `fix/task1-task-contract-20261021-r2` exists but is identical to current `main` at `f517021df2933f1534e39752c4bdc7ba9fa5b7e1`.
- The earlier branch `fix/task1-task-contract-20261021` is one commit behind `main`; do not use it.
- No Inference source or test change was committed. Attempts to create a source blob for the task-correlation change were blocked by the tool safety layer.
- Existing PR #5 is merged. No new PR was opened for this task.

## Existing automation PRs

- FRIDAY #20: open, not merged — https://github.com/surendra2304/FRIDAY/pull/20
- FRIDAY #21: open, not merged — https://github.com/surendra2304/FRIDAY/pull/21

## Blockers

1. The laptop MCP currently returns HTTP 404, so the local checkout cannot be used to run tests.
2. Shell execution through the Oracle Cloud command tool was blocked by the tool safety layer; read-only cloud status works.
3. GitHub source changes were accepted for FRIDAY and the partial Memora changes through Git Data API, but attempts to write the remaining Memora idempotency path and Inference source were blocked by safety checks.
4. GitHub PR creation was blocked by safety checks. Therefore no CI result exists for the new branches.

## Next concrete work

1. On a fresh branch from the latest Inference `main`, implement request/trace/parent correlation on the task request, outcome record, and success/degraded/error responses. Add `tests/test_task_correlation_contract.py`.
2. Finish Memora idempotency: add a bounded `idempotency_key` to the request model, pass both `task_id` and `idempotency_key` into `MemoryWriteService.execute_pipeline`, add correlation metadata to provenance, and test same-task replay plus explicit-key replay.
3. Create PRs for the FRIDAY and Memora branches and the Inference implementation once PR writes are permitted. Do not auto-merge.
4. Run focused tests and lint, record actual counts and results, and only then update this checkpoint to mark them passed.
