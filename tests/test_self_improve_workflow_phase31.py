# -*- coding: utf-8 -*-
"""Unit tests for SelfImprovementWorkflow (Recursive Self-Improvement)."""

from unittest import mock
import pytest

from friday.core.types import Message, Role, SafetyLevel
from friday.tools.builtin.dev_tools import ReadOwnCodebaseTool, RunTestsTool, WriteCodeFileTool
from friday.tools.builtin.git_tools import GitCommitTool, GitPushTool
from friday.tools.registry import ToolRegistry
from friday.workflows.self_improve_workflow import SelfImprovementWorkflow


def test_self_improve_workflow_intent_detection():
    """Workflow identifies requests to add tools or features to FRIDAY."""
    workflow = SelfImprovementWorkflow()
    assert workflow.can_handle("FRIDAY, add a tool to click the mouse")
    assert workflow.can_handle("Add a new tool for downloading youtube audio")
    assert workflow.can_handle("Create a feature that converts currencies")
    assert workflow.can_handle("update your code to support dark mode")
    assert workflow.can_handle("modify yourself to capture multi-screens")
    assert workflow.can_handle("add a feature to yourself")
    assert workflow.can_handle("write a new tool for yourself to extract audio")
    assert not workflow.can_handle("What is the weather today?")
    assert not workflow.can_handle("Hello FRIDAY")


def test_self_improve_workflow_filename_sanitization():
    """Workflow derives valid python filenames from user descriptions."""
    workflow = SelfImprovementWorkflow()
    fn1 = workflow.sanitize_filename("click the mouse")
    assert fn1 == "click_mouse.py"
    fn2 = workflow.sanitize_filename("convert foreign currency exchange rates")
    assert fn2 == "convert_foreign_currency_exchange.py"


def test_self_improve_workflow_authorization_prompt_denied(capsys):
    """Workflow prompts user for authorization; if user denies, does not push."""
    import asyncio

    mock_write = mock.MagicMock(spec=WriteCodeFileTool)
    mock_write.name = "write_code_file"
    mock_write.safety_level = SafetyLevel.SAFE
    mock_write.execute.return_value = mock.MagicMock(is_error=False, content="Wrote code file.")

    mock_test = mock.MagicMock(spec=RunTestsTool)
    mock_test.name = "run_tests"
    mock_push = mock.MagicMock(spec=GitPushTool)
    mock_push.name = "git_push"

    reg = ToolRegistry()
    reg.register(mock_write)
    reg.register(mock_test)
    reg.register(mock_push)

    workflow = SelfImprovementWorkflow(tool_registry=reg)

    with mock.patch("builtins.input", return_value="no"):
        res = asyncio.run(
            workflow.execute_self_improvement(
                user_prompt="Add a tool to click the mouse",
                user_authorized=False,
            )
        )
    assert res["success"] is True
    assert res["pushed"] is False
    assert res["tests_passed"] is False
    assert "Testing and GitHub push were not authorized by the user." in res["summary"]
    mock_write.execute.assert_called_once()
    mock_test.execute.assert_not_called()
    mock_push.execute.assert_not_called()

    captured = capsys.readouterr()
    assert "I have generated the code and written it to click_mouse.py. Do I have your authorization to run tests and push this to GitHub? (yes/no)" in captured.out


def test_self_improve_workflow_authorization_prompt_approved(capsys):
    """Workflow prompts user for authorization; if approved via terminal, tests and push run."""
    import asyncio

    mock_write = mock.MagicMock(spec=WriteCodeFileTool)
    mock_write.name = "write_code_file"
    mock_write.safety_level = SafetyLevel.SAFE
    mock_write.execute.return_value = mock.MagicMock(is_error=False, content="Wrote code file.")

    mock_test = mock.MagicMock(spec=RunTestsTool)
    mock_test.name = "run_tests"
    mock_test.safety_level = SafetyLevel.SAFE
    mock_test.execute.return_value = mock.MagicMock(is_error=False, content="1 passed in 0.05s")

    mock_commit = mock.MagicMock(spec=GitCommitTool)
    mock_commit.name = "git_commit"
    mock_commit.safety_level = SafetyLevel.SAFE
    mock_commit.execute.return_value = mock.MagicMock(is_error=False, content="[main 123] feat: add mouse tool")

    mock_push = mock.MagicMock(spec=GitPushTool)
    mock_push.name = "git_push"
    mock_push.safety_level = SafetyLevel.SAFE
    mock_push.execute.return_value = mock.MagicMock(is_error=False, content="Pushed to origin.")

    reg = ToolRegistry()
    reg.register(mock_write)
    reg.register(mock_test)
    reg.register(mock_commit)
    reg.register(mock_push)

    workflow = SelfImprovementWorkflow(tool_registry=reg)

    with mock.patch("builtins.input", return_value="yes"):
        res = asyncio.run(
            workflow.execute_self_improvement(
                user_prompt="Add a tool to click the mouse",
                user_authorized=False,
            )
        )
    assert res["success"] is True
    assert res["pushed"] is True
    assert res["tests_passed"] is True
    mock_write.execute.assert_called_once()
    mock_test.execute.assert_called_once()
    mock_push.execute.assert_called_once()


def test_self_improve_workflow_execution_loop(tmp_path):
    """Workflow executes indexing, LLM generation, file writing, testing, and git operations."""
    import asyncio

    mock_read = mock.MagicMock(spec=ReadOwnCodebaseTool)
    mock_read.name = "read_own_codebase"
    mock_read.safety_level = SafetyLevel.SAFE
    mock_read.execute.return_value = mock.MagicMock(is_error=False, content="FRIDAY Codebase Map:\n- core/\n- tools/")

    mock_write = mock.MagicMock(spec=WriteCodeFileTool)
    mock_write.name = "write_code_file"
    mock_write.safety_level = SafetyLevel.SAFE
    mock_write.execute.return_value = mock.MagicMock(is_error=False, content="Wrote code file.")

    mock_test = mock.MagicMock(spec=RunTestsTool)
    mock_test.name = "run_tests"
    mock_test.safety_level = SafetyLevel.SAFE
    mock_test.execute.return_value = mock.MagicMock(is_error=False, content="1 passed in 0.05s")

    mock_commit = mock.MagicMock(spec=GitCommitTool)
    mock_commit.name = "git_commit"
    mock_commit.safety_level = SafetyLevel.SAFE
    mock_commit.execute.return_value = mock.MagicMock(is_error=False, content="[main 123456] feat: add mouse tool")

    mock_push = mock.MagicMock(spec=GitPushTool)
    mock_push.name = "git_push"
    mock_push.safety_level = SafetyLevel.SAFE
    mock_push.execute.return_value = mock.MagicMock(is_error=False, content="Pushed to origin.")

    reg = ToolRegistry()
    reg.register(mock_read)
    reg.register(mock_write)
    reg.register(mock_test)
    reg.register(mock_commit)
    reg.register(mock_push)

    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(
        role=Role.ASSISTANT,
        content="```python\nfrom friday.tools.base import BaseTool\nclass ClickMouseTool(BaseTool):\n    name = 'click_mouse'\n```",
    )

    workflow = SelfImprovementWorkflow(tool_registry=reg)

    with mock.patch("friday.llm.factory.create_llm_provider", return_value=mock_llm):
        res = asyncio.run(
            workflow.execute_self_improvement(
                user_prompt="FRIDAY, add a tool to click the mouse",
                user_authorized=True,
            )
        )

        assert res["success"] is True
        assert res["tests_passed"] is True
        assert "click_mouse.py" in res["target_filepath"]
        assert len(res["steps_taken"]) >= 4
        mock_read.execute.assert_called_once()
        mock_write.execute.assert_called_once()
        mock_test.execute.assert_called_once()
        mock_commit.execute.assert_called_once()
        mock_push.execute.assert_called_once()
