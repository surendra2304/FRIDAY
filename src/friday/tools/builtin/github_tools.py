# -*- coding: utf-8 -*-
"""GitHub API automation tools using PyGithub for Git & GitHub Automation."""

from typing import Any, Dict, Optional
import os

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.github_tools")


def _get_github_client(token: Optional[str] = None):
    """Lazily construct PyGithub client."""
    from github import Github, Auth

    tok = token or getattr(get_settings(), "github_token", None) or os.getenv("FRIDAY_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not tok:
        raise ValueError(
            "GitHub token is required. Please set FRIDAY_GITHUB_TOKEN in your environment or .env file."
        )
    auth = Auth.Token(tok)
    return Github(auth=auth)


class ListGitHubIssuesTool(BaseTool):
    """List open or closed issues in a GitHub repository."""

    name = "list_github_issues"
    description = (
        "List issues from a GitHub repository (e.g. 'owner/repo'). Defaults to open issues."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "Full repository name in 'owner/repo' format.",
            },
            "state": {
                "type": "string",
                "description": "Issue state filter: 'open', 'closed', or 'all' (defaults to 'open').",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of issues to return (default: 10).",
            },
        },
        "required": ["repo_name"],
    }

    def execute(
        self,
        repo_name: str,
        state: str = "open",
        limit: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            gh = _get_github_client()
            repo = gh.get_repo(repo_name)
            issues = repo.get_issues(state=state)
            
            output_lines = [f"### Issues for {repo_name} (State: {state})"]
            count = 0
            for issue in issues:
                if issue.pull_request is not None:
                    continue  # skip pull requests
                count += 1
                output_lines.append(f"- [#{issue.number}] {issue.title} (by @{issue.user.login})")
                if count >= max(1, limit):
                    break

            if count == 0:
                output_lines.append("No matching issues found.")

            return ToolResult(
                name=self.name,
                content="\n".join(output_lines),
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.warning(f"Failed to list GitHub issues: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to list GitHub issues for '{repo_name}': {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )


class CreateGitHubIssueTool(BaseTool):
    """Create a new issue on a GitHub repository."""

    name = "create_github_issue"
    description = (
        "Create a new issue in a GitHub repository (e.g. 'owner/repo') with title and body. "
        "Requires authorization."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": "Full repository name in 'owner/repo' format.",
            },
            "title": {
                "type": "string",
                "description": "Title of the issue.",
            },
            "body": {
                "type": "string",
                "description": "Body description of the issue.",
            },
        },
        "required": ["repo_name", "title"],
    }

    def execute(
        self,
        repo_name: str,
        title: str,
        body: Optional[str] = "",
        **kwargs: Any,
    ) -> ToolResult:
        try:
            gh = _get_github_client()
            repo = gh.get_repo(repo_name)
            issue = repo.create_issue(title=title, body=body or "")
            
            return ToolResult(
                name=self.name,
                content=f"Created issue #{issue.number} on {repo_name}: {issue.html_url}",
                is_error=False,
                safety_level=self.safety_level,
                metadata={"issue_number": issue.number, "url": issue.html_url},
            )
        except Exception as e:
            logger.warning(f"Failed to create GitHub issue: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to create issue on '{repo_name}': {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )
