"""Tests for tool system, argument validation, and safety enforcement."""

from typing import Any
import pytest
from friday.core.exceptions import ToolError
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


class DummySensitiveTool(BaseTool):
    name = "edit_file"
    description = "Modifies a file"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "lines": {"type": "integer"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, lines: int = 1, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Edited file: {path} with {lines} lines",
            is_error=False,
            safety_level=self.safety_level,
        )


class FailingTool(BaseTool):
    name = "broken_tool"
    description = "A tool that throws an unexpected error"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> ToolResult:
        raise RuntimeError("Hardware connection severed abruptly.")


def test_system_info_tool():
    tool = SystemInfoTool()
    assert tool.name == "get_system_info"
    assert tool.safety_level == SafetyLevel.SAFE

    result = tool.execute()
    assert not result.is_error
    assert "System Diagnostics Report" in result.content
    assert "OS Information" in result.content


def test_system_info_tool_category_filter():
    tool = SystemInfoTool()
    res_os = tool.execute(category="os")
    assert "OS Information" in res_os.content
    assert "Hardware Architecture" not in res_os.content

    res_hw = tool.execute(category="hardware")
    assert "Hardware Architecture" in res_hw.content
    assert "OS Information" not in res_hw.content


def test_tool_registry_registration():
    reg = ToolRegistry()
    tool = SystemInfoTool()
    reg.register(tool)

    assert reg.get("get_system_info") is tool
    assert len(reg.list_tools()) == 1

    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "get_system_info"


def test_tool_argument_validation():
    tool = DummySensitiveTool()

    # Valid arguments
    valid, err = tool.validate_arguments({"path": "/home/user/file.txt", "lines": 10})
    assert valid
    assert err is None

    # Missing required argument
    invalid_req, err_req = tool.validate_arguments({"lines": 5})
    assert not invalid_req
    assert "Missing required parameter 'path'" in err_req

    # Wrong type (expected integer, got string)
    invalid_type, err_type = tool.validate_arguments({"path": "file.txt", "lines": "five"})
    assert not invalid_type
    assert "expected integer" in err_type


def test_tool_registry_safety_blocking():
    reg = ToolRegistry()
    sensitive_tool = DummySensitiveTool()
    reg.register(sensitive_tool)

    # 1. Without permission -> should return safety block error
    result = reg.execute("edit_file", {"path": "config.txt"}, allow_sensitive=False)
    assert result.is_error
    assert "Safety Block" in result.content

    # 2. With permission -> should execute cleanly
    approved_result = reg.execute("edit_file", {"path": "config.txt", "lines": 3}, allow_sensitive=True)
    assert not approved_result.is_error
    assert "Edited file: config.txt with 3 lines" in approved_result.content


def test_tool_registry_argument_validation_error():
    reg = ToolRegistry()
    tool = DummySensitiveTool()
    reg.register(tool)

    result = reg.execute("edit_file", {"invalid_key": 123}, allow_sensitive=True)
    assert result.is_error
    assert "Missing required parameter 'path'" in result.content


def test_tool_registry_exception_handling():
    reg = ToolRegistry()
    reg.register(FailingTool())

    result = reg.execute("broken_tool", {})
    assert result.is_error
    assert "Hardware connection severed abruptly" in result.content


def test_tool_registry_nonexistent_tool():
    reg = ToolRegistry()
    result = reg.execute("non_existent", {})
    assert result.is_error
    assert "not registered" in result.content
