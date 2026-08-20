# FRIDAY Permanent Project Memory Rule: Diary Maintenance

## Core Architecture
- **Master Index**: `FRIDAY_DIARY.md` (Concise consolidated chronological history with links to all daily files)
- **Daily Raw Chronicles**: `diary/YYYY-MM-DD.md` (Detailed single file per calendar day)
- **Specification Standard**: `FRIDAY_DIARY_SPEC.md`
- **Automation Helper**: `scripts/update_friday_diary.py`
- **Enforcement Pre-Commit Hook**: `scripts/hooks/pre-commit`

## Permanent Requirement
Every meaningful completed engineering task MUST update the diary automatically. This is NOT an optional step.

### Mandatory Workflow
1. **BEFORE TASK**:
   - Read the current diary state and `FRIDAY_DIARY_SPEC.md`.
   - Determine today's actual calendar date (e.g. `2026-08-20`).
   - Inspect relevant historical context.

2. **DURING TASK**:
   Track and record:
   - User requirements and directives
   - Work performed and architectural choices
   - Files created, modified, or deleted
   - Bugs discovered, symptoms, root causes, and fixes (with global Bug # numbering)
   - Important engineering decisions
   - Automated and manual test results
   - Security verifications
   - Git commits and push state
   - Known limitations and current end-of-day state

3. **AFTER TASK**:
   - Update today's `diary/YYYY-MM-DD.md` using the standard schema.
   - Update `FRIDAY_DIARY.md` master index summary.
   - Verify that no secrets, API keys, tokens, passwords, or `.env` entries exist in the diary.
   - Stage and commit the diary alongside code changes, then push according to `github_sync_policy.md`.

### Date & File Rules
- **One File Per Calendar Day**: Exactly one `diary/YYYY-MM-DD.md` per date. Never create duplicate files for the same date. Never invent dates.
- **Master Index Synchronization**: `FRIDAY_DIARY.md` must list every daily file chronologically starting from project inception (**2026-08-18**).

### History & Additive Corrections Rule
- Completed historical daily entries are immutable records of project evolution.
- If an earlier claim or assumption is discovered to be inaccurate, **DO NOT silently rewrite historical files**.
- Record an explicit additive correction in today's entry or under a dedicated `## Corrections to Earlier Information` section explaining:
  * Previous claim
  * Why it was incorrect
  * Empirical evidence
  * Corrected state

### Security Gate
- **Zero Secrets**: Never store API keys, tokens, passwords, private keys, or `.env` contents in `FRIDAY_DIARY.md`, `diary/*.md`, or any repository file.

### Scope of Exemption
- If a task is purely investigatory/exploratory and produces zero changes to source code, tests, architecture, configuration, security, documentation, or behavior, a diary entry is optional.
- If any project artifact is modified, a diary update is **strictly mandatory**.

