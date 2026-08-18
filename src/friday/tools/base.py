"""Base Tool interface with safety classification, schema generation, and argument validation."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from friday.core.types import SafetyLevel, ToolResult


class BaseTool(ABC):
    """Abstract base class for all tools accessible by FRIDAY."""

    name: str
    description: str
    safety_level: SafetyLevel = SafetyLevel.SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert tool definition into OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[{self.safety_level.value}] {self.description}",
                "parameters": self.parameters,
            },
        }

    def validate_arguments(self, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate passed arguments against the tool's parameter schema.

        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str]).
        """
        if not isinstance(arguments, dict):
            return False, f"Arguments for tool '{self.name}' must be a dictionary/object, received: {type(arguments).__name__}"

        schema_props = self.parameters.get("properties", {})
        required_fields = self.parameters.get("required", [])

        # Check for missing required arguments
        for req in required_fields:
            if req not in arguments:
                return False, f"Missing required parameter '{req}' for tool '{self.name}'."

        # Check for unexpected arguments
        for arg_name in arguments:
            if arg_name not in schema_props:
                return False, f"Unexpected parameter '{arg_name}' passed to tool '{self.name}'."

        # Check basic types for provided arguments
        type_mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        for arg_name, arg_val in arguments.items():
            if arg_val is None:
                continue
            prop_def = schema_props.get(arg_name)
            if prop_def and "type" in prop_def:
                expected_type_str = prop_def["type"]
                expected_type = type_mapping.get(expected_type_str)
                # Note: bool is subclass of int in Python, so check bool explicitly
                if expected_type_str == "integer" and isinstance(arg_val, bool):
                    return False, f"Parameter '{arg_name}' expected integer, received boolean."
                elif expected_type and not isinstance(arg_val, expected_type):
                    return False, f"Parameter '{arg_name}' expected {expected_type_str}, received {type(arg_val).__name__}."

        return True, None

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments and return a ToolResult."""
        pass
