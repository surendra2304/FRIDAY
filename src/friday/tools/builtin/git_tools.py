# -*- coding: utf-8 -*-
"""Git CLI automation tools for Phase 24: Git & GitHub Automation."""

import subprocess
import os
from typing import Any, Dict, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.git_tools")


def _run_git_command(args: list[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Execute git command synchronously with timeout."""
    cmd = ["git"] + args
    working_dir = cwd or os.getcwd()
    try:
        proc = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        logger.warning(f"Git command failed: {e}")
        return 1, "", str(e)


class GitStatusTool(BaseTool):
    """Inspect status of working tree and staging area."""

    name = "git_status"
    description = (
        "Get the current git status of the repository, including staged, modified, and untracked files."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "cwd": {
                "type": "string",
                "description": "Optional working directory path (defaults to current repository root).",
            }
        },
        "required": [],
    }

    def execute(self, cwd: Optional[str] = None, **kwargs: Any) -> ToolResult:
        code, out, err = _run_git_command(["status"], cwd=cwd)
        if code != 0:
            return ToolResult(
                name=self.name,
                content=f"Git status failed: {err or out}",
                is_error=True,
                safety_level=self.safety_level,
            )
        return ToolResult(
            name=self.name,
            content=out or "Clean working directory.",
            is_error=False,
            safety_level=self.safety_level,
        )


class GitCommitTool(BaseTool):
    """Stage all changes and commit with a descriptive commit message."""

    name = "git_commit"
    description = (
        "Stage all changes (`git add -A`) and commit them with the specified commit message. "
        "Requires authorization."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The commit message.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional repository path.",
            },
        },
        "required": ["message"],
    }

    def execute(self, message: str, cwd: Optional[str] = None, **kwargs: Any) -> ToolResult:
        msg = (message or "").strip()
        if not msg:
            return ToolResult(
                name=self.name,
                content="Commit message cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # 1. Stage changes
        code, out, err = _run_git_command(["add", "-A"], cwd=cwd)
        if code != 0:
            return ToolResult(
                name=self.name,
                content=f"Failed to stage changes: {err or out}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # 2. Commit
        code, out, err = _run_git_command(["commit", "-m", msg], cwd=cwd)
        if code != 0:
            if "nothing to commit" in (out + err).lower():
                return ToolResult(
                    name=self.name,
                    content="Nothing to commit, working tree clean.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return ToolResult(
                name=self.name,
                content=f"Git commit failed: {err or out}",
                is_error=True,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Committed successfully: {out}",
            is_error=False,
            safety_level=self.safety_level,
        )


class GitPushTool(BaseTool):
    """Push local commits to remote repository origin."""

    name = "git_push"
    description = (
        "Push committed changes to remote repository (e.g. `git push origin HEAD`). "
        "Requires authorization."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (defaults to 'origin').",
            },
            "branch": {
                "type": "string",
                "description": "Branch name (defaults to current branch / HEAD).",
            },
            "cwd": {
                "type": "string",
                "description": "Optional repository path.",
            },
        },
        "required": [],
    }

    def execute(
        self,
        remote: Optional[str] = "origin",
        branch: Optional[str] = None,
        cwd: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        rem = remote or "origin"
        args = ["push", rem]
        if branch:
            args.append(branch)

        code, out, err = _run_git_command(args, cwd=cwd)
        if code != 0:
            return ToolResult(
                name=self.name,
                content=f"Git push failed: {err or out}",
                is_error=True,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Pushed successfully: {out or err}",
            is_error=False,
            safety_level=self.safety_level,
        )
