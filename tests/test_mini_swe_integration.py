"""Tests for mini-SWE-Agent integration and workspace security guardrails."""

import os
from pathlib import Path
import pytest
from friday.core.types import SafetyLevel
from friday.integrations.mini_swe.executor import MiniSWEAgentExecutor
from friday.integrations.mini_swe.safety import CodingWorkspaceGuard


def test_coding_workspace_guard_allows_local_root():
    root = Path(os.getcwd()).resolve()
    guard = CodingWorkspaceGuard(allowed_roots=[root])

    # Subpath inside workspace root allowed
    allowed_sub = root / "src" / "friday" / "agent.py"
    assert guard.is_path_allowed(allowed_sub)

    # Path outside workspace root blocked
    external_path = Path("C:/Windows/System32/drivers/etc/hosts").resolve()
    assert not guard.is_path_allowed(external_path)


def test_coding_workspace_guard_command_sanitization():
    guard = CodingWorkspaceGuard()

    # Dangerous command blocked
    ok, msg, level = guard.validate_command("format C: /fs:NTFS")
    assert not ok
    assert level == SafetyLevel.DANGEROUS

    # Fork bomb blocked
    ok, msg, level = guard.validate_command(":(){ :|:& };:")
    assert not ok

    # Destructive git requires confirmation
    ok, msg, level = guard.validate_command("git reset --hard HEAD~1")
    assert ok
    assert level == SafetyLevel.SENSITIVE

    # Safe test command approved
    ok, msg, level = guard.validate_command("pytest tests/test_agent.py")
    assert ok
    assert level == SafetyLevel.SAFE


def test_mini_swe_executor_blocks_outside_workspace():
    root = Path(os.getcwd()).resolve()
    executor = MiniSWEAgentExecutor(allowed_roots=[root])

    res = executor.execute({
        "task_type": "diagnose",
        "workdir": "C:/Windows/System32",
        "goal": "check system files",
    })
    assert not res.success
    assert "Security Block" in str(res.error)


def test_mini_swe_executor_native_git_inspection():
    executor = MiniSWEAgentExecutor()
    res = executor.execute({"task_type": "inspect_repo"})
    assert res.success
    assert "Git Status" in str(res.output)
