# Task 1 next-run — FRIDAY — 2026-10-22

1. Poll https://github.com/surendra2304/FRIDAY/actions/runs/39674371123 for PR #31 head `358960a1258fbca896452459487581f1239fa138`. Run `39674191089` failed Ruff due import order; follow-up rearranged imports.
2. PR #31 changes `src/friday/agent/router.py` so absent/malformed/out-of-range consensus confidence uses neutral 0.0 instead of fabricated 1.0; regression is in `tests/test_no_invented_telemetry_defaults.py`. Exact head CI pending.
3. PR #22 run `39673561389` completed 2,672 passed, 8 failed, 6 skipped, 23 deselected. Eight failures are listed in checkpoint. The dependency fix added `respx>=0.21.0` in `pyproject.toml`; the AIUniverse schema regressions are on existing PR #22.
4. After PR #31 CI, choose one specific failure from PR #22 (suggested: conversational note incorrectly classified as local Windows directive in `tests/test_voice_instant_routing.py`). Read implementation/test, open a clean branch from current main, add focused fix and verify current-head CI.
5. Laptop execution returns HTTP 404. No local tests. Keep `ui/package-lock.json` unchanged, no auto-merge/force-push, no unmeasured-duration claims.