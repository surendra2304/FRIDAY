"""Tests for Model Context Protocol (MCP) Tool Adapter and Security Integration."""

import pytest
from friday.core.types import SafetyLevel
from friday.tools.mcp.adapter import MCPToolAdapter
from friday.tools.mcp.manager import MCPManager, MCPServerConfig
from friday.tools.registry import ToolRegistry


def test_mcp_adapter_schema_and_execution():
    def mock_server_call(tool_name: str, args: dict):
        return f"Echo from {tool_name}: {args.get('text')}"

    adapter = MCPToolAdapter(
        name="mcp_echo",
        description="Echo input text",
        parameters_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        call_fn=mock_server_call,
        safety_level=SafetyLevel.SAFE,
    )

    assert adapter.name == "mcp_echo"
    assert adapter.safety_level == SafetyLevel.SAFE

    # Register into ToolRegistry
    reg = ToolRegistry()
    reg.register(adapter)
    assert reg.get("mcp_echo") is not None

    # Execute
    res = reg.execute("mcp_echo", {"text": "hello mcp"})
    assert not res.is_error
    assert "Echo from mcp_echo: hello mcp" in res.content


def test_mcp_adapter_security_blocks_unauthorized_sensitive_tool():
    def mock_call(tool_name: str, args: dict):
        return "Deleted resource"

    sensitive_tool = MCPToolAdapter(
        name="mcp_delete_item",
        description="Delete database row",
        parameters_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        call_fn=mock_call,
        safety_level=SafetyLevel.SENSITIVE,
    )

    reg = ToolRegistry()
    reg.register(sensitive_tool)

    # Executing sensitive tool without authorization capability must be blocked by FRIDAY security
    res = reg.execute("mcp_delete_item", {"id": "item_123"})
    assert res.is_error
    assert "Safety Block" in res.content


def test_mcp_manager_detects_sdk_absence_honestly():
    mgr = MCPManager()
    # SDK is not installed in current env
    assert mgr.has_mcp_sdk is False

    # Calling discover with missing SDK returns empty list cleanly without crashing
    cfg = MCPServerConfig(name="test_srv", command=["dummy-mcp"])
    tools = mgr.discover_and_register_tools(cfg)
    assert tools == []
