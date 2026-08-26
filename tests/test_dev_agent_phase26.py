# -*- coding: utf-8 -*-
"""Unit tests for Autonomous Self-Coding Dev Agent."""

import os
from unittest import mock
import pytest

from friday.agents.specialists.developer_agent import DeveloperAgent
from friday.core.config import Settings
from friday.core.types import SafetyLevel, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.tools.builtin.dev_tools import CreateGitBranchTool, RunTestsTool, WriteCodeFileTool
from friday.tools.registry import ToolRegistry
from friday.workflows.dev_workflow import AutonomousDevWorkflow


def test_write_code_file_tool(tmp_path):
    """WriteCodeFileTool writes code to specified path creating parents."""
    tool = WriteCodeFileTool()
    assert tool.safety_level == SafetyLevel.SAFE
    
    target_file = tmp_path / "src" / "sample.py"
    code = "def hello():\n    return 'world'\n"
    res = tool.execute(filepath=str(target_file), code=code)
    
    assert not res.is_error
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == code


def test_run_tests_tool_mocked():
    """RunTestsTool runs pytest subprocess and parses result."""
    tool = RunTestsTool()
    assert tool.safety_level == SafetyLevel.SAFE

    with mock.patch("subprocess.run") as mock_sub:
        mock_sub.return_value = mock.MagicMock(
            returncode=0,
            stdout="5 passed in 0.12s",
            stderr="",
        )
        res = tool.execute(test_path="tests/test_sample.py")
        assert not res.is_error
        assert "PASSED" in res.content
        assert "5 passed" in res.content


def test_create_git_branch_tool_is_sensitive():
    """CreateGitBranchTool is marked SENSITIVE and invokes git checkout -b."""
    tool = CreateGitBranchTool()
    assert tool.safety_level == SafetyLevel.SENSITIVE

    with mock.patch("friday.tools.builtin.git_tools._run_git_command") as mock_git:
        mock_git.return_value = (0, "Switched to a new branch 'fix/issue-4'", "")
        res = tool.execute(branch_name="fix/issue-4")
        assert not res.is_error
        assert "Created and checked out git branch 'fix/issue-4'" in res.content
        mock_git.assert_called_once_with(["checkout", "-b", "fix/issue-4"], cwd=None)


def test_developer_agent_instantiation():
    """DeveloperAgent initializes with developer role and tools."""
    mock_llm = MockLLMProvider()
    tools = ToolRegistry()
    dev_agent = DeveloperAgent(llm_provider=mock_llm, tool_registry=tools)
    
    assert dev_agent.role == "developer"
    assert "write_code_file" in dev_agent.allowed_tools
    assert "run_tests" in dev_agent.allowed_tools
    assert "create_git_branch" in dev_agent.allowed_tools


@pytest.mark.anyio
async def test_autonomous_dev_workflow_success_flow():
    """AutonomousDevWorkflow extracts issue, creates branch, writes fix, runs tests, and commits/pushes."""
    registry = ToolRegistry()
    
    branch_tool = mock.MagicMock(spec=CreateGitBranchTool)
    branch_tool.name = "create_git_branch"
    branch_tool.execute.return_value = ToolResult(name="create_git_branch", content="Branch created", is_error=False)
    
    gh_tool = mock.MagicMock()
    gh_tool.name = "list_github_issues"
    gh_tool.execute.return_value = ToolResult(name="list_github_issues", content="[#4] Fix math bug", is_error=False)
    
    test_tool = mock.MagicMock(spec=RunTestsTool)
    test_tool.name = "run_tests"
    test_tool.execute.return_value = ToolResult(name="run_tests", content="All tests passed", is_error=False)
    
    commit_tool = mock.MagicMock()
    commit_tool.name = "git_commit"
    commit_tool.execute.return_value = ToolResult(name="git_commit", content="Committed", is_error=False)
    
    push_tool = mock.MagicMock()
    push_tool.name = "git_push"
    push_tool.execute.return_value = ToolResult(name="git_push", content="Pushed to remote", is_error=False)
    
    registry.register(branch_tool)
    registry.register(gh_tool)
    registry.register(test_tool)
    registry.register(commit_tool)
    registry.register(push_tool)

    mock_llm = MockLLMProvider()
    dev_agent = DeveloperAgent(llm_provider=mock_llm, tool_registry=registry)

    workflow = AutonomousDevWorkflow(
        developer_agent=dev_agent,
        tool_registry=registry,
        repo_name="surendra2304/FRIDAY",
    )

    prompt = "Please fix issue #4 in the repository"
    assert workflow.can_handle(prompt)
    assert workflow.extract_issue_number(prompt) == 4

    result = await workflow.execute_issue_fix(prompt)
    assert result["success"] is True
    assert result["issue_id"] == 4
    assert result["branch"] == "fix/issue-4"
    assert result["tests_passed"] is True
    branch_tool.execute.assert_called_once()
    commit_tool.execute.assert_called_once()
    push_tool.execute.assert_called_once()
