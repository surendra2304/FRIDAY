# FRIDAY Permanent Project Memory Rule: GitHub Synchronization

**GitHub is the permanent remote source for the FRIDAY project.**
- Repository: https://github.com/surendra2304/FRIDAY
- Default branch: `main`

For every meaningful FRIDAY development task, the standard automatic workflow is:

1. **INSPECT**
2. **IMPLEMENT**
3. **TEST**
4. **VERIFY**
5. **UPDATE FRIDAY_DIARY.md**
6. **REVIEW CHANGES**
7. **SECURITY CHECK**
8. **COMMIT**
9. **PUSH TO origin/main**
10. **VERIFY GITHUB SYNC**
11. **VERIFY CLEAN WORKTREE**

**Critical Rules:**
- **Do NOT ask permission**: Commit and push completed tasks automatically without waiting for explicit user permission. Do not leave completed work only on the local machine.
- **What to Push**: Source code, tests, docs, config templates, architecture, security fixes, diary, project metadata, scripts.
- **What NEVER to Push**: `.env`, real API keys, passwords, tokens, local secrets, temporary artifacts (`scratch/`), local brains/logs.
- **Commit Messages**: Use conventional commits (e.g. `feat(...)`, `fix(...)`, `docs(...)`, `refactor(...)`, `test(...)`, `security(...)`).
- **Push Verification**: Always verify local `main` matches `origin/main` after a push. If a push fails, diagnose and retry if safe. Do NOT use `--force` unless explicitly authorized by the user.

**MANDATORY PUSH GUARD:**
NEVER automatically commit or push a completed development task when required tests or verification are failing.
If tests or required verification fail:
- Do NOT push the failed implementation.
- Record the failure in `FRIDAY_DIARY.md`.
- Record the likely cause if known.
- Fix the issue before committing/pushing.
- Only push after the required validation succeeds.
- Do not treat a partial implementation as complete.

**EXCEPTIONS:**
- Documentation-only changes may use an appropriate lightweight validation instead of the full application test suite when running the full suite is unnecessary. However, the change must still be reviewed and validated before push.

**SECURITY GATE:**
Before every automatic commit:
- Verify `.env` is not tracked (e.g., using `git ls-files .env` which MUST return no output).
- Inspect staged changes for accidental secrets.
- Do not commit API keys, passwords, tokens, cookies, or local secrets.
- Do not force-push (`git push --force` or `--force-with-lease`) unless explicitly authorized by the user.
- Do not rewrite Git history.

**DIARY GATE:**
Before pushing meaningful work:
- Update `docs/FRIDAY_DIARY.md`.
- Record tests/verification.
- Record known failures if any.
- Record final commit/push state.
- The diary must never claim successful completion when verification failed. (The diary and Git history must remain consistent.)
