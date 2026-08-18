"""Tests for tool system and safety enforcement."""

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
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Edited file: {kwargs.get('path')}",
            is_error=False,
            safety_level=self.safety_level,
        )


def test_system_info_tool():
    tool = SystemInfoTool()
    assert tool.name == "get_system_info"
    assert tool.safety_level == SafetyLevel.SAFE

    result = tool.execute()
    assert not result.is_error
    assert "System Information" in result.content
    assert "os" in result.content


def test_tool_registry_registration():
    reg = ToolRegistry()
    tool = SystemInfoTool()
    reg.register(tool)

    assert reg.get("get_system_info") is tool
    assert len(reg.list_tools()) == 1

    schemas = reg.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "get_system_info"


def test_tool_registry_safety_blocking():
    reg = ToolRegistry()
    sensitive_tool = DummySensitiveTool()
    reg.register(sensitive_tool)

    # 1. Without permission -> should return safety block error
    result = reg.execute("edit_file", {"path": "config.txt"}, allow_sensitive=False)
    assert result.is_error
    assert "Safety Block" in result.content

    # 2. With permission -> should execute cleanly
    approved_result = reg.execute("edit_file", {"path": "config.txt"}, allow_sensitive=True)
    assert not approved_result.is_error
    assert "Edited file: config.txt" in approved_result.content


def test_tool_registry_nonexistent_tool():
    reg = ToolRegistry()
    result = reg.execute("non_existent", {})
    assert result.is_error
    assert "not found" in result.content
