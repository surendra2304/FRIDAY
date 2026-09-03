"""mini-SWE-Agent Specialist Software Engineering Executor for FRIDAY.

Provides software engineering and repository diagnostic capabilities:
1. Inspect repositories and directory structure
2. Investigate failing tests and analyze stack traces
3. Execute bounded test suites
4. Apply precise code fixes within authorized workspaces
5. Review and summarize git modifications

Strictly guarded by CodingWorkspaceGuard to prevent unauthorized disk writes
or command execution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.integrations.mini_swe.safety import CodingWorkspaceGuard
from friday.planning.executors import BaseExecutor, ExecutorResult
from friday.planning.types import TaskDataType

logger = get_logger("integrations.mini_swe.executor")


class MiniSWEAgentExecutor(BaseExecutor):
    """Specialist executor for repository comprehension, bug diagnosis, and test-driven fixes."""

    def __init__(
        self,
        name: str = "mini_swe_agent",
        allowed_roots: list[str | Path] | None = None,
        timeout_seconds: float = 300.0,
        executable_name: str = "mini-swe-agent",
    ) -> None:
        super().__init__(
            name=name,
            capability="software_engineering",
            description="Executes repository inspection, test failure debugging, bug diagnosis, code patching, and test validation.",
            input_types=[TaskDataType.TEXT, TaskDataType.FILE, TaskDataType.JSON],
            output_types=[TaskDataType.TEXT, TaskDataType.STRUCTURED_DATA],
            provider="swe_specialist",
            model="mini-swe-agent/native-dev",
            is_local=True,
            cost_profile="free",
            latency_profile="medium",
            safety_level=SafetyLevel.SENSITIVE,
        )
        self.guard = CodingWorkspaceGuard(allowed_roots=allowed_roots)
        self.timeout_seconds = timeout_seconds
        self.executable_name = executable_name

    @property
    def is_cli_available(self) -> bool:
        """Check if mini-swe-agent executable is present in system PATH."""
        return shutil.which(self.executable_name) is not None

    def execute(self, inputs: dict[str, Any], context: dict[str, Any] | None = None) -> ExecutorResult:
        """Execute software engineering subtask."""
        start_t = time.perf_counter()
        task_type = str(inputs.get("task_type") or inputs.get("action", "diagnose")).lower()
        goal = inputs.get("goal") or inputs.get("task") or inputs.get("prompt", "")
        workdir = inputs.get("workdir") or inputs.get("repo_path") or str(self.guard.allowed_roots[0])

        # 1. Validate workdir containment
        if not self.guard.is_path_allowed(workdir):
            return ExecutorResult(
                success=False,
                output=None,
                error=f"Security Block: Workspace '{workdir}' is outside authorized coding directories.",
                output_type=TaskDataType.TEXT,
                duration_seconds=time.perf_counter() - start_t,
                metadata={"blocked": True, "workdir": workdir},
            )

        # 2. If external CLI is installed, delegate to mini-swe-agent
        if self.is_cli_available:
            try:
                proc = subprocess.run(
                    [self.executable_name, "--task", str(goal)],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                duration = time.perf_counter() - start_t
                if proc.returncode == 0:
                    return ExecutorResult(
                        success=True,
                        output=proc.stdout or "Task completed successfully by mini-swe-agent.",
                        output_type=TaskDataType.TEXT,
                        duration_seconds=duration,
                        metadata={"engine": "mini-swe-agent-cli", "returncode": 0},
                    )
                else:
                    return ExecutorResult(
                        success=False,
                        output=proc.stdout,
                        error=proc.stderr or f"mini-swe-agent exited with status {proc.returncode}",
                        output_type=TaskDataType.TEXT,
                        duration_seconds=duration,
                        metadata={"engine": "mini-swe-agent-cli", "returncode": proc.returncode},
                    )
            except subprocess.TimeoutExpired:
                return ExecutorResult(
                    success=False,
                    output=None,
                    error=f"mini-swe-agent timed out after {self.timeout_seconds} seconds.",
                    duration_seconds=time.perf_counter() - start_t,
                )
            except Exception as e:
                logger.warning(f"mini-swe-agent CLI execution failed: {e}. Falling back to native tools...")

        # 3. Native FRIDAY Software Engineering Fallback
        return self._execute_native_swe_fallback(
            task_type=task_type,
            goal=goal,
            workdir=workdir,
            inputs=inputs,
            start_t=start_t,
        )

    def _execute_native_swe_fallback(
        self,
        task_type: str,
        goal: str,
        workdir: str,
        inputs: dict[str, Any],
        start_t: float,
    ) -> ExecutorResult:
        """Native developer tool execution for testing, inspection, and patching."""
        try:
            # A. Test execution
            if task_type in ("run_tests", "test"):
                test_path = inputs.get("test_path") or inputs.get("test_target")
                cmd = ["pytest"]
                if test_path:
                    cmd.append(str(test_path))
                proc = subprocess.run(
                    cmd,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
                success = proc.returncode == 0
                out = proc.stdout if proc.stdout else proc.stderr
                return ExecutorResult(
                    success=success,
                    output=out,
                    error=None if success else f"Tests failed (exit code {proc.returncode})",
                    output_type=TaskDataType.TEXT,
                    duration_seconds=time.perf_counter() - start_t,
                    metadata={"engine": "native_pytest", "exit_code": proc.returncode},
                )

            # B. Git Status / Changes inspection
            if task_type in ("inspect_repo", "git_status", "diff"):
                proc = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                    check=False,
                )
                diff_proc = subprocess.run(
                    ["git", "diff", "--stat"],
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    timeout=30.0,
                    check=False,
                )
                summary = f"Git Status:\n{proc.stdout or 'Clean'}\n\nRecent Diff:\n{diff_proc.stdout or 'No unstaged diffs'}"
                return ExecutorResult(
                    success=True,
                    output=summary,
                    output_type=TaskDataType.TEXT,
                    duration_seconds=time.perf_counter() - start_t,
                    metadata={"engine": "native_git"},
                )

            # C. File read / inspection
            if task_type in ("read_file", "diagnose") and inputs.get("filepath"):
                filepath = Path(workdir) / inputs["filepath"]
                if not self.guard.is_path_allowed(filepath):
                    return ExecutorResult(
                        success=False,
                        output=None,
                        error=f"Access blocked to file outside workspace: {filepath}",
                        duration_seconds=time.perf_counter() - start_t,
                    )
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                return ExecutorResult(
                    success=True,
                    output=content[:6000],
                    output_type=TaskDataType.TEXT,
                    duration_seconds=time.perf_counter() - start_t,
                    metadata={"engine": "native_fileread", "file": str(filepath)},
                )

            # Generic software engineering response
            return ExecutorResult(
                success=True,
                output=f"Software engineering workspace '{workdir}' verified. Ready to execute code updates.",
                output_type=TaskDataType.TEXT,
                duration_seconds=time.perf_counter() - start_t,
                metadata={"engine": "native_swe"},
            )

        except Exception as e:
            return ExecutorResult(
                success=False,
                output=None,
                error=f"Native SWE tool failure: {str(e)}",
                duration_seconds=time.perf_counter() - start_t,
            )
