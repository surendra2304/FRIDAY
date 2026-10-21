# Task 1 next-run — FRIDAY — 2026-10-22

1. Poll https://github.com/surendra2304/FRIDAY/actions/runs/39674934153 for PR #31 head `56e400aaf1ed759f2053621a012a163c9d9653b8`. Dependency install, Ruff and syntax/installer checks passed; pytest was still running.
2. PR #31 source `src/friday/agent/router.py` now treats absent/malformed/out-of-range provider confidence as neutral 0.0, not fabricated 1.0. Regression: `tests/test_no_invented_telemetry_defaults.py`; `pyproject.toml` now declares `respx>=0.21.0`.
3. PR #22 CI `39673561389` failed with 2,672 passed, 8 failed, 6 skipped, 23 deselected. Failure names/symptoms are in checkpoint. Fix one at a time with narrow tests.
4. Suggested next fix: ordinary “save a note about deployment” is incorrectly classified as local Windows directive; inspect `tests/test_voice_instant_routing.py::TestClassifyInstantCommand::test_conversation_does_not_route_locally` and the classifier.
5. Local tests unavailable (laptop MCP HTTP 404). Preserve `ui/package-lock.json`; no auto-merge/force-push or unmeasured time claims.