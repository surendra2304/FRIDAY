# Task 1 next-run instructions — FRIDAY

Last updated: 2026-10-20T23:01:52Z

Read .github/friday-continuation/task-1-checkpoint.md before coding. Resume branch automation/friday-universe-task-1; continue existing implementation rather than restarting repository review.

## Previous run evidence

- Result: completed
- Active coding seconds: 1926
- Coding passes: 20
- Source paths changed against main: 5

### Changed source paths

- rc/friday/llm/ai_universe_provider.py
- src/friday/tools/ai_universe_client.py
- tests/test_ai_universe_provider.py
- tests/tools/test_ai_universe_client.py
- ui/package-lock.json

### Runner failures or blockers

- None recorded by the runner.

## Detailed continuation notes from the previous coding pass

# Task 1 next-run instructions — FRIDAY

Read `task-1-checkpoint.md` and continue from its next concrete action; do not repeat broad repository reconnaissance. Preserve the unrelated pre-existing modification to `ui/package-lock.json`. Work only in FRIDAY. Do not commit, push, open PRs, or alter Git configuration.

**First coding action:** Add deterministic ask/debate tests for HTTP 200 JSON objects whose fields fail `AIUniverseResponse` validation. Verify the `AIUniverseTool.execute()` error result exposes the validation failure and closes the owned `httpx.AsyncClient` in both ordinary synchronous invocation and invocation from an already-running event loop. Use `httpx.MockTransport`; change implementation only if the regression demonstrates a defect.

Current relevant context:

- `AIUniverseClient._parse_response()` in `src/friday/tools/ai_universe_client.py` requires a JSON object and constructs `AIUniverseResponse`; `AIUniverseTool.execute()` converts ordinary exceptions into visible error `ToolResult`s.
- `tests/tools/test_ai_universe_client.py` now covers ask/debate malformed JSON in HTTP 200 responses across ordinary and active-loop invocation (4 cases). Each verifies visible parse failure and owned-client cleanup.
- It also covers ask/debate HTTP 422/503 errors, cancellation propagation and cleanup, and malformed agent roster responses.
- Earlier reliability implementation remains in `src/friday/llm/ai_universe_provider.py`, `tests/test_ai_universe_provider.py`, and `src/friday/tools/ai_universe_client.py`.
- PR #15 remains uninspected because `gh pr view 15 ...` previously failed with exit code 4 when `GH_TOKEN` was unavailable. Do not make GitHub writes or modify allocator code.
- Preserve the unrelated pre-existing change in `ui/package-lock.json`.

Latest validation results:

- `.venv/bin/python -m pytest -q tests/test_ai_universe_provider.py tests/test_fallback_chain_provider.py tests/tools/test_ai_universe_client.py` — **71 passed, 0 failed** in 7.92s.
- `.venv/bin/ruff check src/friday/tools/ai_universe_client.py tests/tools/test_ai_universe_client.py src/friday/llm/ai_universe_provider.py tests/test_ai_universe_provider.py` — **passed, 0 findings**.
- `.venv/bin/python -m mypy src/friday/tools/ai_universe_client.py src/friday/llm/ai_universe_provider.py --no-incremental` — **passed, 0 issues**.
- `git diff --check` — **passed, 0 whitespace errors**.
- No live services or credentials were used. Full-suite and UI checks were not run.

After the tests, run the four validation commands above. Before ending, rewrite both continuation files with exact changed paths, behavior, command results, numeric pass/fail counts, unresolved work, blockers, and the next precise coding action. Leave `ui/package-lock.json` untouched, do not modify allocator code, and make no GitHub writes.


## First action next run

Read the checkpoint and these previous notes, inspect the branch diff, run the focused tests for the last implementation, fix failures, and implement the next highest-impact feature or regression fix. Record exact commands/results and revise both handoff files before ending.
