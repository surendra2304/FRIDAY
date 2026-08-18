"""Tool Registry for tool registration, discovery, schema export, validation, and execution."""

from typing import Any, Dict, List, Optional
from friday.core.exceptions import ToolError
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.registry")


class ToolRegistry:
    """Central registry for managing agent tools and enforcing safety policies."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        if not tool.name:
            raise ToolError("Cannot register tool without a valid name")
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool registration: '{tool.name}'")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: '{tool.name}' [Safety: {tool.safety_level.value}]")

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_schemas(self, max_safety: Optional[SafetyLevel] = None) -> List[Dict[str, Any]]:
        """Export OpenAI-compatible schemas for all registered tools.

        Optionally filters tools by maximum safety tolerance.
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append(tool.to_openai_schema())
        return schemas

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        tool_call_id: str = "",
        allow_sensitive: bool = False,
    ) -> ToolResult:
        """Validate and execute a tool by name with safety checks.

        Args:
            name: Tool name.
            arguments: Dictionary of arguments.
            tool_call_id: Associated LLM tool call ID.
            allow_sensitive: Whether sensitive/dangerous execution is approved by user.

        Returns:
            ToolResult containing execution status and output.
        """
        tool = self.get(name)
        if not tool:
            err_msg = f"Error: Tool '{name}' is not registered or available in FRIDAY's tool registry."
            logger.error(err_msg)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=err_msg,
                is_error=True,
                safety_level=SafetyLevel.SAFE,
            )

        # Validate arguments against parameter schema
        is_valid, validation_err = tool.validate_arguments(arguments)
        if not is_valid:
            err_msg = f"Invalid arguments for tool '{name}': {validation_err}"
            logger.warning(err_msg)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=err_msg,
                is_error=True,
                safety_level=tool.safety_level,
            )

        # Check safety permissions
        if tool.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS) and not allow_sensitive:
            err_msg = (
                f"Safety Block: Tool '{name}' is classified as '{tool.safety_level.value}' "
                f"and requires explicit user confirmation before execution."
            )
            logger.warning(err_msg)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=err_msg,
                is_error=True,
                safety_level=tool.safety_level,
            )

        try:
            logger.info(f"Executing tool '{name}' (Safety: {tool.safety_level.value}) with args: {arguments}")
            result = tool.execute(**arguments)
            result.tool_call_id = tool_call_id
            return result
        except Exception as e:
            logger.exception(f"Exception during tool '{name}' execution: {e}")
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"Tool execution encountered an internal error: {str(e)}",
                is_error=True,
                safety_level=tool.safety_level,
            )
