# -*- coding: utf-8 -*-
"""Unit tests for ReadOwnCodebaseTool and SelfDevAgent (Phase 31: Recursive Self-Improvement)."""

from pathlib import Path
from unittest import mock
import pytest

from friday.agents.specialists.self_dev_agent import SelfDevAgent
from friday.core.types import SafetyLevel
from friday.tools.builtin.dev_tools import ReadOwnCodebaseTool


def test_read_own_codebase_tool_safety_and_name():
    """ReadOwnCodebaseTool must be marked as SAFE."""
    tool = ReadOwnCodebaseTool()
    assert tool.safety_level == SafetyLevel.SAFE
    assert tool.name == "read_own_codebase"


def test_read_own_codebase_scans_real_repo():
    """ReadOwnCodebaseTool scans src/friday and returns a structured map."""
    tool = ReadOwnCodebaseTool()
    res = tool.execute()
    assert not res.is_error
    assert "FRIDAY Codebase Architecture Map" in res.content
    assert "core" in res.content
    assert "agent" in res.content
    assert "tools" in res.content


def test_read_own_codebase_mock_directory(tmp_path):
    """ReadOwnCodebaseTool properly handles custom directory and docstrings."""
    pkg = tmp_path / "mock_pkg"
    pkg.mkdir()
    f1 = pkg / "module_a.py"
    f1.write_text('"""Module A handles data transforms."""\ndef foo(): pass\n', encoding="utf-8")
    f2 = pkg / "module_b.py"
    f2.write_text('# No docstring\ndef bar(): pass\n', encoding="utf-8")

    tool = ReadOwnCodebaseTool()
    res = tool.execute(root_dir=str(pkg))
    assert not res.is_error
    assert "Module A handles data transforms" in res.content
    assert "module_a.py" in res.content
    assert "module_b.py" in res.content
    assert "2 Python modules" in res.content


def test_self_dev_agent_initialization():
    """SelfDevAgent initializes with specialized architecture instructions and allowed tools."""
    agent = SelfDevAgent()
    assert agent.role == "self_developer"
    assert "Recursive Self-Improvement" in agent.instructions
    assert "read_own_codebase" in agent.allowed_tools
    assert "write_code_file" in agent.allowed_tools
    assert "run_tests" in agent.allowed_tools
    assert "create_git_branch" in agent.allowed_tools
