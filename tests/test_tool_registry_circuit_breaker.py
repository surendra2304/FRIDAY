from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class FailingTool(BaseTool):
    name = "failing_tool"
    description = "Returns an execution error for circuit breaker coverage."
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(
            name=self.name,
            content="temporary failure",
            is_error=True,
            safety_level=self.safety_level,
        )


def test_default_circuit_breaker_persists_failures_between_calls():
    registry = ToolRegistry()
    registry._circuit_breaker.max_failures = 2
    registry.register(FailingTool())

    assert registry.execute("failing_tool", {}).is_error
    assert registry.execute("failing_tool", {}).is_error

    blocked = registry.execute("failing_tool", {})
    assert blocked.is_error
    assert "circuit breaker" in blocked.content.lower()


def test_default_circuit_breaker_resets_after_success():
    registry = ToolRegistry()
    registry._circuit_breaker.max_failures = 2
    tool = FailingTool()
    registry.register(tool)

    assert registry.execute("failing_tool", {}).is_error
    tool.execute = lambda **kwargs: ToolResult(
        name=tool.name, content="ok", is_error=False, safety_level=tool.safety_level
    )
    assert not registry.execute("failing_tool", {}).is_error

    tool.execute = lambda **kwargs: ToolResult(
        name=tool.name, content="temporary failure", is_error=True, safety_level=tool.safety_level
    )
    assert registry.execute("failing_tool", {}).is_error
    assert not registry._circuit_breaker.is_open("failing_tool")
