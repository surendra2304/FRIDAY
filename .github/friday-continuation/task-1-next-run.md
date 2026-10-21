# Task 1 next-run — FRIDAY — 2026-10-22

1. Poll https://github.com/surendra2304/FRIDAY/actions/runs/39672647603 on the current branch head `9f659c3edc3902d83968414204003a57a3d402d6`. Ruff and syntax checks passed; pytest was still running.
2. Earlier run `39672146283` at `1113ff8ac1696016b9b5762c66651f74dccba3a8` failed collection because `respx` was not declared. Commit `9f659c3edc3902d83968414204003a57a3d402d6` adds `respx>=0.21.0` to `pyproject.toml` dev dependencies.
3. Once full CI is green, add regression for wrong-type `key_evidence` values on ask/debate and normal/active-loop invocation, checking error ToolResult and AsyncClient closure. If CI is red, inspect logs and repair exact cause.
4. Continue existing PR #22; don't duplicate it. Preserve unrelated `ui/package-lock.json`; don't merge automatically. Local tests not run because laptop MCP endpoint returns HTTP 404. Do not claim unmeasured active time.