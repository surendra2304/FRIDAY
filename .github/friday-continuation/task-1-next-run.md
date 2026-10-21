# Task 1 next-run instructions — FRIDAY (2026-10-22)

Read `.github/friday-continuation/task-1-checkpoint.md` first.

1. Check CI run https://github.com/surendra2304/FRIDAY/actions/runs/39672146283 for commit `1113ff8ac1696016b9b5762c66651f74dccba3a8`; it was in progress when last inspected. If failed, inspect job logs and fix root cause.
2. This run committed `tests/tools/test_ai_universe_client.py` at `1113ff8ac1696016b9b5762c66651f74dccba3a8`: four schema-invalid JSON object cases, ask/debate × normal/active-loop invocation, asserting ToolResult error and AsyncClient closure.
3. Next code change after CI settles: test wrong-type `key_evidence` fields for ask/debate and both invocation modes; run focused pytest/Ruff if a runner becomes available.
4. Preserve unrelated `ui/package-lock.json`. Existing PRs #25, #23, #22 remain open; inspect current heads/CI before creating any PR.
5. No local tests ran due laptop MCP HTTP 404. Update all handoff files only with exact evidence; don't claim unmeasured active minutes.