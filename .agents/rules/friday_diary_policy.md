# FRIDAY Permanent Project Memory Rule: Diary Maintenance

**FRIDAY_DIARY.md is the permanent, chronological, authoritative history of the entire FRIDAY project.**

For EVERY future FRIDAY development task, automatically follow this workflow:

1. **UNDERSTAND TASK**
2. **INSPECT CURRENT STATE**
3. **IMPLEMENT**
4. **TEST**
5. **RECORD IMPORTANT CHANGES IN FRIDAY_DIARY.md**
6. **RECORD BUGS/FIXES/DECISIONS**
7. **RECORD TEST RESULTS**
8. **RECORD COMMIT**
9. **RECORD GITHUB PUSH**
10. **VERIFY DIARY IS CURRENT**

**Critical Rules:**
- Do NOT wait for the user to tell you to update the diary.
- Do NOT ask permission to update it.
- Do NOT skip it because a task is small.
- **Source of Truth**: Treat `docs/FRIDAY_DIARY.md` as the permanent project-history source of truth. `README.md` is for the CURRENT project overview.
- **Security**: NEVER store secrets (API keys, passwords, access tokens, cookies, private credentials) in the diary or project memory. The Gemini API key remains only in the local `.env`. Use `[REDACTED]`.
- **Accuracy**: Never claim a feature is implemented unless it is actually implemented. Always distinguish between `IMPLEMENTED`, `REAL-TESTED`, `MOCK-TESTED`, `PARTIAL`, `PLACEHOLDER`, `PLANNED`, and `FUTURE`.
- **Permanence**: This is an INDEFINITE project. FRIDAY is never considered permanently finished. Continue maintaining the diary for every future phase and development session.
