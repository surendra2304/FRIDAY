"""Tests for tool system, argument validation, and safety enforcement."""

from typing import Any
import pytest
from friday.core.exceptions import ToolError
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.builtin import (
    SystemInfoTool,
    TimeDateTool,
    CalculatorTool,
    FileReaderTool,
    FileListingTool,
)
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


def test_tool_argument_validation_optional_none():
    tool = DummySensitiveTool()
    
    # Optional parameter 'lines' explicitly set to None (null) should be valid
    valid, err = tool.validate_arguments({"path": "file.txt", "lines": None})
    assert valid
    assert err is None


def test_tool_registry_get_schemas_max_safety():
    reg = ToolRegistry()
    
    safe_tool = SystemInfoTool()
    sensitive_tool = DummySensitiveTool()
    
    reg.register(safe_tool)
    reg.register(sensitive_tool)
    
    # 1. max_safety=SAFE -> only safe tool returned
    safe_schemas = reg.get_schemas(max_safety=SafetyLevel.SAFE)
    assert len(safe_schemas) == 1
    assert safe_schemas[0]["function"]["name"] == "get_system_info"
    
    # 2. max_safety=SENSITIVE -> both tools returned
    sensitive_schemas = reg.get_schemas(max_safety=SafetyLevel.SENSITIVE)
    assert len(sensitive_schemas) == 2


class DummyDefaultTool(BaseTool):
    name = "dummy_default_tool"
    description = "A dummy tool to test parameter defaults."
    parameters = {
        "type": "object",
        "properties": {
            "required_val": {"type": "string"},
            "optional_val": {"type": "integer"},
        },
        "required": ["required_val"],
    }
    
    def execute(self, required_val: str, optional_val: int = 42, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"required={required_val}, optional={optional_val}",
        )


def test_tool_argument_validation_unexpected_arg():
    tool = DummySensitiveTool()
    valid, err = tool.validate_arguments({"path": "file.txt", "lines": 5, "unexpected_param": True})
    assert not valid
    assert "Unexpected parameter 'unexpected_param'" in err


def test_tool_registry_optional_arg_null_filtering():
    reg = ToolRegistry()
    tool = DummyDefaultTool()
    reg.register(tool)
    
    # Passing optional_val as None explicitly should trigger the default value of 42
    result = reg.execute("dummy_default_tool", {"required_val": "hello", "optional_val": None})
    assert not result.is_error
    assert "optional=42" in result.content


def test_time_date_tool():
    tool = TimeDateTool()
    result = tool.execute()
    assert not result.is_error
    assert result.safety_level == SafetyLevel.SAFE
    assert "Current Local Date" in result.content
    assert "Current Local Time" in result.content
    assert "Day of the Week" in result.content
    assert "Unix Timestamp" in result.content


def test_calculator_tool_valid():
    tool = CalculatorTool()
    # Basic math
    res1 = tool.execute("2 + 3 * 4")
    assert not res1.is_error
    assert res1.content == "14"
    
    # Exponentiation & Parentheses
    res2 = tool.execute("(2 + 3) ** 2")
    assert not res2.is_error
    assert res2.content == "25"
    
    # Float decimals formatting
    res3 = tool.execute("7 / 2")
    assert not res3.is_error
    assert res3.content == "3.5"


def test_calculator_tool_division_by_zero():
    tool = CalculatorTool()
    res = tool.execute("5 / 0")
    assert res.is_error
    assert "Division by zero" in res.content


def test_calculator_tool_security_rejections():
    tool = CalculatorTool()
    
    # Python code statement injection
    res1 = tool.execute("import os; os.system('echo 1')")
    assert res1.is_error
    assert "Invalid expression" in res1.content
    
    # Calling functions/objects
    res2 = tool.execute("eval('1+1')")
    assert res2.is_error
    assert "Unsupported AST node" in res2.content
    
    # Large exponent DoS prevention
    res3 = tool.execute("9999 ** 9999")
    assert res3.is_error
    assert "Exponent too large" in res3.content or "combination too large" in res3.content


def test_file_reader_tool_valid():
    import os
    test_file_name = "temp_test_read.txt"
    test_content = "Hello, FRIDAY file reader!\nLine 2 content."
    
    with open(test_file_name, "w", encoding="utf-8") as f:
        f.write(test_content)
        
    try:
        tool = FileReaderTool()
        result = tool.execute(path=test_file_name)
        assert not result.is_error
        assert "Hello, FRIDAY file reader!" in result.content
        assert "Line 2 content." in result.content
        
        # Max bytes truncation
        trunc_result = tool.execute(path=test_file_name, max_bytes=5)
        assert not trunc_result.is_error
        assert "Hello" in trunc_result.content
        assert "FRIDAY" not in trunc_result.content
    finally:
        if os.path.exists(test_file_name):
            os.remove(test_file_name)


def test_file_reader_tool_security_and_binary():
    tool = FileReaderTool()
    
    # Path traversal block
    result_traversal = tool.execute(path="../outside.txt")
    assert result_traversal.is_error
    assert "Security Error" in result_traversal.content
    
    # Nonexistent file
    result_missing = tool.execute(path="nonexistent_file_abc_123.txt")
    assert result_missing.is_error
    assert "does not exist" in result_missing.content


def test_file_listing_tool_valid():
    tool = FileListingTool()
    
    # List workspace root
    result = tool.execute(path=".")
    assert not result.is_error
    assert "Directory Listing" in result.content
    assert "README.md" in result.content
    assert "pyproject.toml" in result.content


def test_file_listing_tool_traversal_and_errors():
    tool = FileListingTool()
    
    # Path traversal block
    res1 = tool.execute(path="../")
    assert res1.is_error
    assert "Security Error" in res1.content
    
    # Non-existent directory
    res2 = tool.execute(path="nonexistent_folder_abc")
    assert res2.is_error
    assert "does not exist" in res2.content



