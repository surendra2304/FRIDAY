# Claude Code - FRIDAY Universe Ultimate Project Rules

## 1. Agent Orchestration and Follow-Up (CRITICAL)
When delegating work to specialized agents (e.g., planner, tdd-guide, architect, etc.):
- **Never Fire-and-Forget**: When you assign a task to a subagent, you MUST explicitly wait for and verify its output. Do not assume the work is done just because you launched the agent.
- **Active Follow-Up**: Continuously monitor agent status (using logs or terminal output). If it stalls or produces 0 work, intervene immediately.
- **Verification Step**: Before marking any task as complete, you must read the code, tests, or artifacts produced by the subagent to confirm it actually executed the work cleanly.
- **Parallel Speed**: Launch multiple agents simultaneously for independent tasks to work fast, but you remain the master orchestrator.

## 2. The 3-Strike Anti-Loop Protocol
To prevent getting stuck in infinite debugging loops:
- **Strike 1**: Try your initial fix.
- **Strike 2**: If the error persists, read the exact traceback, inspect the surrounding code context, and try a different approach.
- **Strike 3**: If it fails a third time, **STOP**. Do not blindly try again. You must completely rethink the architecture, rewrite the failing function from scratch, or halt and explicitly ask the user for guidance.

## 3. Mandatory Test & Verification (TDD)
- You must NEVER confidently declare a feature 'done' without running the tests.
- Always run pytest for the specific module you modified.
- If tests fail, automatically fix them before returning to the user.

## 4. Git Checkpointing for Resilience
- Before starting a massive refactor or delegating a destructive task to an agent, run git add . && git commit -m "chore: auto-checkpoint before risky changes". 
- If an agent completely destroys a file or goes off track, use git restore to revert it instantly instead of trying to manually fix their mess.

## 5. Context Hygiene (High-Pressure Performance)
- Do not blindly dump 5,000-line files into your context window. 
- Use grep / ipgrep / d to surgically find the exact functions or classes you need to modify.
- Break massive tasks into focused agent assignments, wait for their return, and stitch the results together cleanly.

## 6. Execution Speed & Autonomy
- Do not ask for permission for routine tasks (creating files, running tests, installing standard dependencies). Just do it.
- Work fast, work cleanly, and verify your own work.
