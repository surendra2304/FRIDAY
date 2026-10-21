# Task 1 next-run — FRIDAY — 2026-10-22

1. Poll https://github.com/surendra2304/FRIDAY/actions/runs/39674934153 for PR #31 head `56e400aaf1ed759f2053621a012a163c9d9653b8`. Dependency install, Ruff, syntax and installer checks passed; pytest was in progress at last check.
2. PR #31 changes `src/friday/agent/router.py` so missing/malformed/out-of-range confidence becomes 0.0, not fabricated 1.0. Regression in `tests/test_no_invented_telemetry_defaults.py`; `pyproject.toml` now declares `respx>=0.21.0`.
3. PR #22 CI `39673561389` ended with 2,672 passed, 8 failed, 6 skipped, 23 deselected. Failed cases and exact behavior are in checkpoint. Pick one failure, inspect implementation/tests, fix minimally and verify by CI.
4. Suggested next: inspect `tests/test_voice_instant_routing.py::TestClassifyInstantCommand::test_conversation_does_not_route_locally`; an ordinary “save a note about deployment” is incorrectly classified as local Windows directive.
5. Local tests unavailable (laptop MCP HTTP 404). Preserve unrelated `ui/package-lock.json`; no merge/force-push or unmeasured-duration claim.