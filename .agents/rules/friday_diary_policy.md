--------------------------------------------------
FRIDAY DIARY POLICY
--------------------------------------------------

Before beginning any meaningful task:

1. Read:
   - .agents/rules/github_sync_policy.md
   - .agents/rules/friday_diary_policy.md
   - relevant existing project instructions

2. Inspect the latest relevant diary entry.

During a task:

3. Keep track of:
   - work performed
   - problems discovered
   - root causes
   - fixes
   - tests
   - verification
   - security
   - Git commits
   - known limitations

After a meaningful task is completed:

4. Automatically update:
   docs/FRIDAY_DIARY.md

5. Diary MUST be day-wise:
   ## YYYY-MM-DD

6. Within each day, use sections such as:
   ### Work Completed
   ### Problems Found
   ### Root Cause
   ### Fixes Implemented
   ### Verification
   ### Tests
   ### Security
   ### Git / GitHub
   ### Known Limitations
   ### Next Planned Work

7. Never fabricate test results.

8. Never change:
   NOT VERIFIED
   PARTIAL
   BLOCKED
   MOCK
   PLACEHOLDER

   into VERIFIED unless real evidence exists.

9. Historical failures MUST remain preserved.

10. If a later fix supersedes an earlier failure, preserve both entries and
    clearly record the correction.

11. Never store API keys, passwords, tokens, private keys, or other secrets
    in the diary or project memory.

12. Never store .env contents in project memory.

13. Never print secrets in reports.

14. After a meaningful completed task:
    - update diary
    - inspect git diff
    - commit according to github_sync_policy
    - push according to github_sync_policy
    - verify HEAD == origin/main
    - verify worktree clean

15. For documentation-only or tiny exploratory tasks:
    do NOT create unnecessary commits.

16. Before giving a final response to the user:
    verify that the diary reflects the actual completed state.

17. The diary is the canonical human-readable engineering history.

18. Project memory/rules store the permanent operating policies.

19. Never confuse project memory with diary history.

20. Never claim "automatic diary update" unless this policy file exists and is
    being followed in the current task.

--------------------------------------------------
END FRIDAY DIARY POLICY
--------------------------------------------------
