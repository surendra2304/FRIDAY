# -*- coding: utf-8 -*-
"""Developer Tools for Autonomous Self-Coding Autonomous Self-Coding.

Provides safe & sensitive tools for writing code files, running tests via pytest,
and creating git branches.
"""

from pathlib import Path
import os
import subprocess
from typing import Any, Dict, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.dev_tools")


class WriteCodeFileTool(BaseTool):
    """Write or overwrite source code into a file safely with parent directory creation."""

    name = "write_code_file"
    description = (
        "Write or overwrite code to a specified file path. "
        "Automatically creates parent directories if they do not exist."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "filepath": {
                "type": "string",
                "description": "Relative or absolute path of the file to write to.",
            },
            "code": {
                "type": "string",
                "description": "Source code or text content to write into the file.",
            },
        },
        "required": ["filepath", "code"],
    }

    def execute(self, filepath: str = "", code: str = "", **kwargs: Any) -> ToolResult:
        clean_path = (filepath or "").strip()
        if not clean_path:
            return ToolResult(
                name=self.name,
                content="Error: No filepath provided.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            target = Path(clean_path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
            logger.info(f"Successfully wrote code file '{target}' ({len(code)} chars)")
            return ToolResult(
                name=self.name,
                content=f"Successfully wrote {len(code)} characters to '{clean_path}'.",
                is_error=False,
                safety_level=self.safety_level,
                metadata={"filepath": str(target), "bytes_written": len(code.encode('utf-8'))},
            )
        except Exception as e:
            logger.error(f"Failed to write code file '{clean_path}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to write code file: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )


class RunTestsTool(BaseTool):
    """Execute pytest test suites via subprocess and return pass/fail diagnostics."""

    name = "run_tests"
    description = (
        "Execute pytest on a specified test path or file (e.g. 'tests/test_foo.py') and return stdout/stderr results."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "test_path": {
                "type": "string",
                "description": "Optional test file or directory path (defaults to running non-live/hardware unit tests).",
            },
            "extra_args": {
                "type": "string",
                "description": "Optional extra pytest arguments (e.g. '-k test_name -v').",
            },
        },
        "required": [],
    }

    def execute(self, test_path: Optional[str] = None, extra_args: Optional[str] = None, **kwargs: Any) -> ToolResult:
        cmd = ["pytest"]
        if test_path and test_path.strip():
            cmd.append(test_path.strip())
        else:
            cmd.extend(["-m", "not live and not hardware", "-q"])

        if extra_args and extra_args.strip():
            cmd.extend(extra_args.strip().split())

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            output = proc.stdout.strip() or proc.stderr.strip()
            success = proc.returncode == 0
            status_str = "PASSED" if success else f"FAILED (exit code {proc.returncode})"
            logger.info(f"Pytest execution {status_str} for command: {' '.join(cmd)}")
            return ToolResult(
                name=self.name,
                content=f"Pytest Execution {status_str}:\n{output}",
                is_error=not success,
                safety_level=self.safety_level,
                metadata={
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "command": cmd,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                name=self.name,
                content="Error: Pytest execution timed out after 120 seconds.",
                is_error=True,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"Failed to execute pytest: {e}")
            return ToolResult(
                name=self.name,
                content=f"Error executing pytest: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )


class CreateGitBranchTool(BaseTool):
    """Create and checkout a new Git branch. Marked SENSITIVE."""

    name = "create_git_branch"
    description = (
        "Create and switch to a new git branch in the repository. "
        "Requires authorization as a SENSITIVE repository modification."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "branch_name": {
                "type": "string",
                "description": "Name of the new git branch to create and checkout (e.g. 'fix/issue-4').",
            },
            "cwd": {
                "type": "string",
                "description": "Optional repository working directory path.",
            },
        },
        "required": ["branch_name"],
    }

    def execute(self, branch_name: str = "", cwd: Optional[str] = None, **kwargs: Any) -> ToolResult:
        clean_name = (branch_name or "").strip()
        if not clean_name:
            return ToolResult(
                name=self.name,
                content="Error: No branch name provided.",
                is_error=True,
                safety_level=self.safety_level,
            )

        from friday.tools.builtin.git_tools import _run_git_command

        code, out, err = _run_git_command(["checkout", "-b", clean_name], cwd=cwd)
        if code != 0:
            return ToolResult(
                name=self.name,
                content=f"Failed to create git branch '{clean_name}': {err or out}",
                is_error=True,
                safety_level=self.safety_level,
            )

        logger.info(f"Created and checked out git branch '{clean_name}'")
        return ToolResult(
            name=self.name,
            content=f"Created and checked out git branch '{clean_name}'.",
            is_error=False,
            safety_level=self.safety_level,
            metadata={"branch_name": clean_name},
        )


class ReadOwnCodebaseTool(BaseTool):
    """Scan the FRIDAY codebase structure and generate an architectural module map."""

    name = "read_own_codebase"
    description = (
        "Scan the src/friday directory structure and return a map of modules, packages, "
        "and files so the LLM understands FRIDAY's internal architecture to write new features."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "root_dir": {
                "type": "string",
                "description": "Optional root directory to scan (defaults to 'src/friday').",
            },
            "include_descriptions": {
                "type": "boolean",
                "description": "Whether to extract module-level docstrings from Python files (default: True).",
            },
        },
        "required": [],
    }

    def execute(
        self,
        root_dir: Optional[str] = None,
        include_descriptions: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        import ast

        target_root = Path(root_dir) if root_dir else Path(__file__).resolve().parent.parent.parent
        # If target_root is tools (parent.parent), go up one more to friday package root
        if target_root.name != "friday" and (target_root / "friday").is_dir():
            target_root = target_root / "friday"
        elif target_root.name == "builtin":
            target_root = Path(__file__).resolve().parent.parent.parent

        # Ensure we are pointing at src/friday
        if not target_root.exists() or not target_root.is_dir():
            # Try current working directory src/friday
            candidate = Path("src/friday").resolve()
            if candidate.exists() and candidate.is_dir():
                target_root = candidate
            else:
                return ToolResult(
                    name=self.name,
                    content=f"Error: Target root directory '{target_root}' not found.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        modules_map = []
        file_count = 0

        for path in sorted(target_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            file_count += 1
            rel_path = path.relative_to(target_root.parent)
            docstring = ""
            if include_descriptions:
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    tree = ast.parse(content)
                    doc = ast.get_docstring(tree)
                    if doc:
                        docstring = doc.strip().split("\n")[0]
                except Exception:
                    pass

            entry = f"- {rel_path.as_posix()}"
            if docstring:
                entry += f": {docstring}"
            modules_map.append(entry)

        summary = (
            f"FRIDAY Codebase Architecture Map ({file_count} Python modules in '{target_root.name}'):\n"
            + "\n".join(modules_map)
        )

        return ToolResult(
            name=self.name,
            content=summary,
            is_error=False,
            safety_level=self.safety_level,
        )
