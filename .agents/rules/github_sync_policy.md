# FRIDAY Permanent Project Memory Rule: GitHub Synchronization

**GitHub is the permanent remote source for the FRIDAY project.**
- Repository: https://github.com/surendra2304/FRIDAY
- Default branch: `main`

For every meaningful FRIDAY development task, the standard automatic workflow is:

1. **INSPECT**
2. **IMPLEMENT**
3. **TEST**
4. **UPDATE FRIDAY_DIARY.md**
5. **REVIEW CHANGES**
6. **COMMIT**
7. **PUSH TO origin/main**
8. **VERIFY GITHUB SYNC**
9. **VERIFY CLEAN WORKTREE**

**Critical Rules:**
- **Do NOT ask permission**: Commit and push completed tasks automatically without waiting for explicit user permission. Do not leave completed work only on the local machine.
- **What to Push**: Source code, tests, docs, config templates, architecture, security fixes, diary, project metadata, scripts.
- **What NEVER to Push**: `.env`, real API keys, passwords, tokens, local secrets, temporary artifacts (`scratch/`), local brains/logs.
- **Security Check**: ALWAYS run a check equivalent to `git ls-files .env` (which must return no output) and inspect staged changes for accidental secrets before committing.
- **Commit Messages**: Use conventional commits (e.g. `feat(...)`, `fix(...)`, `docs(...)`, `refactor(...)`, `test(...)`, `security(...)`).
- **Push Verification**: Always verify local `main` matches `origin/main` after a push. If a push fails, diagnose and retry if safe. Do NOT use `--force` unless explicitly authorized by the user.
- **Diary Sync**: The diary (`docs/FRIDAY_DIARY.md`) and Git history must remain consistent. Always update the diary with the work performed, bugs/fixes, and push status before/during the commit.
