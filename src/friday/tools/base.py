"""Base Tool interface with safety classification and schema generation."""

from abc import ABC, abstractmethod
from typing import Any, Dict
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

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given arguments and return a ToolResult."""
        pass
