# Contributing to FRIDAY

Thank you for your interest in contributing to FRIDAY!

## Workflow

1. **Branch Naming**: Please use descriptive branch names for your work (e.g., `feature/add-new-tool`, `bugfix/fix-audio-streaming`).
2. **Local Testing**: Before opening a Pull Request, you must run the following checks locally. CI will enforce these checks.
   - Run the linter: `ruff check src/ tests/`
   - Run type checking: `mypy src/`
   - Run the test suite: `pytest -m "not live and not hardware"`
3. **Pull Requests**: All tests must pass for your PR to be merged. Do not bypass failing tests; fix the underlying issues.

Thank you for your contributions!
