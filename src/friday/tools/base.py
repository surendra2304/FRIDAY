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
                if isinstance(p_type, str):
                    prop_def["type"] = [p_type, "null"]
                elif isinstance(p_type, list):
                    if "null" not in p_type:
                        prop_def["type"] = list(p_type) + ["null"]
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

        type_mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        # Check for unexpected arguments and simple type coercion
        if schema_props:
            for arg_name, arg_val in list(arguments.items()):
                if arg_name not in schema_props:
                    return False, f"Unexpected parameter '{arg_name}' passed to tool '{self.name}'."

                if arg_val is None:
                    continue

                prop_def = schema_props[arg_name]
                expected_type = prop_def.get("type")
                if isinstance(expected_type, list):
                    non_null = [t for t in expected_type if t != "null"]
                    expected_type = non_null[0] if non_null else None

                # Simple type coercion
                if expected_type == "integer" and isinstance(arg_val, str):
                    try:
                        arguments[arg_name] = int(arg_val)
                    except ValueError:
                        return False, f"Parameter '{arg_name}' expected integer, received str."
                elif expected_type == "number" and isinstance(arg_val, str):
                    try:
                        arguments[arg_name] = float(arg_val)
                    except ValueError:
                        return False, f"Parameter '{arg_name}' expected number, received str."
                elif expected_type == "boolean" and isinstance(arg_val, str):
                    arguments[arg_name] = arg_val.lower() == "true"

        # Check basic types for provided arguments
        for arg_name, arg_val in arguments.items():
            if arg_val is None:
                continue
            prop_def = schema_props.get(arg_name)
            if prop_def and "type" in prop_def:
                expected_type_spec = prop_def["type"]
                if isinstance(expected_type_spec, list):
                    allowed_types: list[type] = []
                    for t in expected_type_spec:
                        if t != "null" and t in type_mapping:
                            mapped = type_mapping[t]
                            if isinstance(mapped, tuple):
                                allowed_types.extend(mapped)
                            else:
                                allowed_types.append(mapped)
                    if isinstance(arg_val, bool) and "boolean" not in expected_type_spec:
                        return False, f"Parameter '{arg_name}' expected one of {expected_type_spec}, received boolean."
                    if allowed_types and not isinstance(arg_val, tuple(allowed_types)):
                        return False, f"Parameter '{arg_name}' expected one of {expected_type_spec}, received {type(arg_val).__name__}."
                elif isinstance(expected_type_spec, str):
                    expected_type_val = type_mapping.get(expected_type_spec)
                    # Note: bool is subclass of int in Python, so check bool explicitly
                    if expected_type_spec == "integer" and isinstance(arg_val, bool):
                        return False, f"Parameter '{arg_name}' expected integer, received boolean."
                    elif expected_type_val and not isinstance(arg_val, expected_type_val):
                        return False, f"Parameter '{arg_name}' expected {expected_type_spec}, received {type(arg_val).__name__}."

        return True, None

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments and return a ToolResult."""
