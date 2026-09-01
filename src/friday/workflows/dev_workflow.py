from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from friday.agents.specialists.developer_agent import DeveloperAgent
from friday.core.logging import get_logger
from friday.tools.builtin.dev_tools import (
    CreateGitBranchTool,
    RunTestsTool,
)
from friday.tools.builtin.git_tools import GitCommitTool, GitPushTool
from friday.tools.builtin.github_tools import ListGitHubIssuesTool
from friday.tools.registry import ToolRegistry

logger = get_logger("workflows.dev_workflow")


class AutonomousDevWorkflow:
    """End-to-end workflow to resolve repository issues autonomously."""

    def __init__(
        self,
        developer_agent: DeveloperAgent | None = None,
        tool_registry: ToolRegistry | None = None,
        repo_name: str | None = None,
    ) -> None:
        self.developer_agent = developer_agent
        self.tool_registry = tool_registry or ToolRegistry()
        self.repo_name = repo_name or os.getenv("FRIDAY_GITHUB_REPO") or "surendra2304/FRIDAY"

    def can_handle(self, user_prompt: str) -> bool:
        """Check if user prompt matches an autonomous dev issue-resolution goal."""
        if not user_prompt:
            return False
        pattern = r"\b(?:fix|resolve|implement|address)\s+issue\s*#?(?P<issue_id>\d+)\b"
        return bool(re.search(pattern, user_prompt, re.IGNORECASE))

    def extract_issue_number(self, user_prompt: str) -> int | None:
        """Extract target issue ID number from user instruction."""
        pattern = r"\b(?:fix|resolve|implement|address)\s+issue\s*#?(?P<issue_id>\d+)\b"
        match = re.search(pattern, user_prompt, re.IGNORECASE)
        if match:
            return int(match.group("issue_id"))
        return None

    async def execute_issue_fix(
        self,
        user_prompt: str,
        repo_name: str | None = None,
        branch_prefix: str = "fix/issue-",
    ) -> dict[str, Any]:
        """Orchestrate autonomous resolution of a specified issue."""
        target_repo = repo_name or self.repo_name
        issue_id = self.extract_issue_number(user_prompt)
        if not issue_id:
            return {
                "success": False,
                "error": "Could not identify issue number from prompt.",
                "steps_taken": [],
            }

        steps: list[str] = []
        logger.info(f"Initiating autonomous fix for Issue #{issue_id} in repo '{target_repo}'")

        # Step 1: Create and checkout git branch
        branch_name = f"{branch_prefix}{issue_id}"
        branch_tool = self.tool_registry.get("create_git_branch") or CreateGitBranchTool()
        branch_res = branch_tool.execute(branch_name=branch_name)
        steps.append(f"Branch Creation: {branch_res.content}")

        # Step 2: Fetch issue details from GitHub
        issue_desc = f"Issue #{issue_id} from {target_repo}"
        gh_tool = self.tool_registry.get("list_github_issues") or ListGitHubIssuesTool()
        gh_res = gh_tool.execute(repo_name=target_repo, limit=20)
        if not gh_res.is_error:
            steps.append(f"GitHub Issue Context: Retrieved issues list for '{target_repo}'.")
            issue_desc = f"GitHub Issue #{issue_id} in {target_repo}:\n{gh_res.content}"
        else:
            steps.append(f"GitHub Issue Context: Note - {gh_res.content}")

        # Step 3: Route to DeveloperAgent to write code and verify
        dev_output = ""
        if self.developer_agent:
            from friday.agents.base_agent import AgentTask
            task = AgentTask(
                goal=f"Resolve GitHub issue #{issue_id}: {user_prompt}\nContext: {issue_desc}",
                context={"repo": target_repo, "issue_id": issue_id, "branch": branch_name},
            )
            task_res = await self.developer_agent.execute_task(task)
            dev_output = task_res.output
            steps.append(f"Developer Agent Fix: {dev_output}")
        else:
            steps.append("Developer Agent Fix: DeveloperAgent not directly attached, using dev tools.")

        # Step 4: Run Tests to verify fix
        test_tool = self.tool_registry.get("run_tests") or RunTestsTool()
        test_res = test_tool.execute()
        steps.append(f"Verification: {test_tool.name} result -> {test_res.content[:200]}")

        tests_passed = not test_res.is_error

        # Step 5: Commit and Push if tests pass
        commit_res_content = ""
        push_res_content = ""
        if tests_passed:
            commit_tool = self.tool_registry.get("git_commit") or GitCommitTool()
            commit_res = commit_tool.execute(message=f"fix: resolve issue #{issue_id} autonomously")
            commit_res_content = commit_res.content
            steps.append(f"Git Commit: {commit_res_content}")

            push_tool = self.tool_registry.get("git_push") or GitPushTool()
            push_res = push_tool.execute(branch=branch_name)
            push_res_content = push_res.content
            steps.append(f"Git Push: {push_res_content}")

            return {
                "success": True,
                "issue_id": issue_id,
                "branch": branch_name,
                "tests_passed": True,
                "steps_taken": steps,
                "summary": f"Autonomously resolved issue #{issue_id} on branch '{branch_name}'. Tests passed and changes were committed.",
            }
        else:
            return {
                "success": False,
                "issue_id": issue_id,
                "branch": branch_name,
                "tests_passed": False,
                "steps_taken": steps,
                "error": "Automated tests failed after fix attempt.",
                "summary": f"Attempted fix for issue #{issue_id} on branch '{branch_name}', but tests failed. Changes not pushed.",
            }
