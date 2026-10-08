"""Git CLI automation tools for Git & GitHub Automation."""

import os
import subprocess
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.git_tools")


class GitRepoRefused(ValueError):
    """Raised when a git operation is refused before git is invoked."""


def _find_git_root(start: Path) -> Path | None:
    """Walk upwards from *start* looking for a checkout."""
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _resolve_git_dir(cwd: str | None, *, mutating: bool) -> Path:
    """Decide which directory git runs in, and refuse the dangerous ones.

    This exists because the git tools used to run in ``os.getcwd()`` when the
    model did not name a directory.  For a user who starts FRIDAY from a
    project that is convenient; when the working directory is FRIDAY's own
    checkout it means "create a branch" silently moved *FRIDAY's* HEAD, and
    "push" published *FRIDAY's* commits.  Neither is what the sentence asked
    for, and neither was confirmed.

    The rule is therefore: resolve the directory, find the repository it
    belongs to, and refuse to *change* FRIDAY's own repository unless the
    operator has explicitly allowed self-modification.  Read-only commands
    (``git status``) are allowed anywhere so diagnostics keep working.
    """
    from friday.security.workspace_policy import PathPolicyError, shared_policy

    policy = shared_policy()
    base = Path(cwd).expanduser() if cwd else Path.cwd()
    try:
        resolved = policy.resolve(base, for_write=mutating, must_exist=True, label="cwd")
    except PathPolicyError as exc:
        raise GitRepoRefused(str(exc)) from exc

    repo_root = _find_git_root(resolved)
    if repo_root is None:
        raise GitRepoRefused(f"'{resolved}' is not inside a git repository.")

    if mutating and not policy.allow_self_modification:
        for protected in policy.protected_roots:
            if repo_root == protected or repo_root in protected.parents or protected.is_relative_to(repo_root):
                raise GitRepoRefused(
                    f"Refused: '{repo_root}' is FRIDAY's own repository (it contains {protected}). "
                    f"Changing FRIDAY's own git state from a tool call is disabled; pass an explicit "
                    f"'cwd' for the repository you meant, or set FRIDAY_ALLOW_SELF_MODIFICATION=true "
                    f"if you really mean to let the agent branch, commit or push its own source."
                )
    return resolved


def _run_git_command(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
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

    def execute(self, cwd: str | None = None, **kwargs: Any) -> ToolResult:
        try:
            resolved = _resolve_git_dir(cwd, mutating=False)
        except GitRepoRefused as exc:
            return ToolResult(name=self.name, content=f"Git status refused: {exc}", is_error=True,
                              safety_level=self.safety_level)
        code, out, err = _run_git_command(["status"], cwd=str(resolved))
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

    def execute(self, message: str, cwd: str | None = None, **kwargs: Any) -> ToolResult:
        msg = (message or "").strip()
        if not msg:
            return ToolResult(
                name=self.name,
                content="Commit message cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # 1. Stage changes
        try:
            resolved = _resolve_git_dir(cwd, mutating=True)
        except GitRepoRefused as exc:
            return ToolResult(name=self.name, content=f"Git commit refused: {exc}", is_error=True,
                              safety_level=self.safety_level)
        cwd = str(resolved)
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
        remote: str | None = "origin",
        branch: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        rem = remote or "origin"
        args = ["push", rem]
        if branch:
            args.append(branch)

        try:
            resolved = _resolve_git_dir(cwd, mutating=True)
        except GitRepoRefused as exc:
            return ToolResult(name=self.name, content=f"Git push refused: {exc}", is_error=True,
                              safety_level=self.safety_level)
        code, out, err = _run_git_command(args, cwd=str(resolved))
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
