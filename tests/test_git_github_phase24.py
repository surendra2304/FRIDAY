# -*- coding: utf-8 -*-
"""Unit tests for Phase 24: Git & GitHub Automation."""

import pytest
from unittest.mock import MagicMock, patch

from friday.tools.builtin.git_tools import GitStatusTool, GitCommitTool, GitPushTool
from friday.tools.builtin.github_tools import ListGitHubIssuesTool, CreateGitHubIssueTool
from friday.core.types import SafetyLevel


def test_git_status_tool():
    tool = GitStatusTool()
    assert tool.name == "git_status"
    assert tool.safety_level == SafetyLevel.SAFE

    with patch("friday.tools.builtin.git_tools._run_git_command", return_value=(0, "On branch main\nnothing to commit", "")):
        result = tool.execute()
        assert not result.is_error
        assert "On branch main" in result.content


def test_git_commit_tool():
    tool = GitCommitTool()
    assert tool.name == "git_commit"
    assert tool.safety_level == SafetyLevel.SENSITIVE

    with patch("friday.tools.builtin.git_tools._run_git_command") as mock_run:
        mock_run.side_effect = [
            (0, "", ""),  # git add -A
            (0, "[main abc1234] feat: test commit", ""),  # git commit -m
        ]
        result = tool.execute(message="feat: test commit")
        assert not result.is_error
        assert "Committed successfully" in result.content


def test_git_push_tool():
    tool = GitPushTool()
    assert tool.name == "git_push"
    assert tool.safety_level == SafetyLevel.SENSITIVE

    with patch("friday.tools.builtin.git_tools._run_git_command", return_value=(0, "To origin/main", "")):
        result = tool.execute(remote="origin", branch="main")
        assert not result.is_error
        assert "Pushed successfully" in result.content


def test_github_list_issues_tool():
    tool = ListGitHubIssuesTool()
    assert tool.name == "list_github_issues"
    assert tool.safety_level == SafetyLevel.SAFE

    mock_gh = MagicMock()
    mock_repo = MagicMock()
    mock_issue1 = MagicMock(number=101, title="Fix audio buffer", pull_request=None)
    mock_issue1.user.login = "developer"
    mock_repo.get_issues.return_value = [mock_issue1]
    mock_gh.get_repo.return_value = mock_repo

    with patch("friday.tools.builtin.github_tools._get_github_client", return_value=mock_gh):
        result = tool.execute(repo_name="surendra2304/FRIDAY")
        assert not result.is_error
        assert "#101" in result.content
        assert "Fix audio buffer" in result.content


def test_github_create_issue_tool():
    tool = CreateGitHubIssueTool()
    assert tool.name == "create_github_issue"
    assert tool.safety_level == SafetyLevel.SENSITIVE

    mock_gh = MagicMock()
    mock_repo = MagicMock()
    mock_created = MagicMock(number=102, html_url="https://github.com/surendra2304/FRIDAY/issues/102")
    mock_repo.create_issue.return_value = mock_created
    mock_gh.get_repo.return_value = mock_repo

    with patch("friday.tools.builtin.github_tools._get_github_client", return_value=mock_gh):
        result = tool.execute(
            repo_name="surendra2304/FRIDAY",
            title="Bug in VAD sensitivity",
            body="Voice activation threshold needs adjustment",
        )
        assert not result.is_error
        assert "Created issue #102" in result.content
