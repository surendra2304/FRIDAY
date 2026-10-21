# Task 1 next-run instructions — FRIDAY (2026-10-22)

1. Poll CI https://github.com/surendra2304/FRIDAY/actions/runs/39672647603 for commit `9f659c3edc3902d83968414204003a57a3d402d6` on existing PR #22. It was installing dependencies at last check. Do not create a duplicate PR.
2. Prior run `39672146283` failed pytest collection because `respx` was not declared in `pyproject.toml` dev dependencies. Commit `9f659c3edc3902d83968414204003a57a3d402d6` adds `respx>=0.21.0` and should allow collection to proceed.
3. Code/test commit `1113ff8ac1696016b9b5762c66651f74dccba3a8` adds four cases in `tests/tools/test_ai_universe_client.py` for schema-invalid `confidence`, ask/debate × normal/active-loop invocation. The failing first run didn't reach these cases because collection failed earlier.
4. If current CI is green, add ask/debate × normal/active-loop regressions for wrong-type `key_evidence`. If red, inspect run logs and fix exact cause.
5. Preserve unrelated `ui/package-lock.json`. PR #25 and #23 remain open; PR #22 contains this branch's work. Local tests did not run because laptop MCP returns HTTP 404. Record exact checks and don't claim unmeasured active time.