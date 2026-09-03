"""Base Tool interface with safety classification, schema generation, and argument validation."""

from abc import ABC, abstractmethod
from typing import Any

from friday.core.types import SafetyLevel, ToolResult


class BaseTool(ABC):
    """Abstract base class for all tools accessible by FRIDAY."""

    name: str
    description: str
    safety_level: SafetyLevel = SafetyLevel.SAFE
    # Additional metadata for robust tool orchestration
    risk_level: str = "SAFE"  # Options: SAFE, SENSITIVE, DANGEROUS
    auth_requirement: str = "NONE"  # NONE, USER, ADMIN
    timeout: int = 30  # seconds, per‑tool execution timeout
    retry_policy: dict[str, Any] = {"max_attempts": 3, "backoff": 1}
    idempotency: bool = False
    side_effects: list[str] = []
    verification_method: Any = None  # Callable[[Any], bool] – optional custom verification

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert tool definition into OpenAI function calling format."""
        import copy

        params = copy.deepcopy(self.parameters)
        props = params.get("properties", {})
        required = set(params.get("required", []))
        for key, prop_def in props.items():
            if key not in required and isinstance(prop_def, dict):
                p_type = prop_def.get("type")
                if isinstance(p_type, list):
                    non_null = [t for t in p_type if t != "null"]
                    prop_def["type"] = non_null[0] if non_null else "string"
                prop_def["nullable"] = True

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[{self.safety_level.value}] {self.description}",
                "parameters": params,
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> tuple[bool, str | None]:
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
