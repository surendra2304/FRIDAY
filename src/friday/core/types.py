"""Core type definitions and data models for FRIDAY."""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Role(str, Enum):
    """Message role definitions."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SafetyLevel(str, Enum):
    """Tool safety classification levels.

    SAFE:
        Read-only, non-destructive, non-disclosive operations.
        Can execute automatically.

    SENSITIVE:
        State-altering, file write, outbound communication, package installation.
        Requires explicit user confirmation before execution.

    DANGEROUS:
        Destructive, raw shell execution, file deletion, security modifications.
        Requires explicit confirmation and strict gating.
    """
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    DANGEROUS = "DANGEROUS"


class ToolCall(BaseModel):
    """Representation of an LLM tool call request."""
    id: str = Field(default="", description="Unique identifier for the tool call")
    name: str = Field(..., description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments passed to the tool")


class ToolResult(BaseModel):
    """Result of a tool execution."""
    tool_call_id: str = Field(default="", description="Identifier of the matching tool call")
    name: str = Field(..., description="Name of the executed tool")
    content: str = Field(..., description="Textual or JSON output of the execution")
    is_error: bool = Field(default=False, description="Whether the tool execution encountered an error")
    safety_level: SafetyLevel = Field(default=SafetyLevel.SAFE, description="Safety tier of the tool")


class Message(BaseModel):
    """Standard conversational message model."""
    role: Role = Field(..., description="Role of the message sender")
    content: str = Field(default="", description="Text content of the message")
    name: Optional[str] = Field(default=None, description="Optional author or tool name")
    tool_calls: Optional[List[ToolCall]] = Field(default=None, description="Tool calls requested by assistant")
    tool_call_id: Optional[str] = Field(default=None, description="ID of the tool call this message responds to")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")

    def to_provider_dict(self) -> Dict[str, Any]:
        """Convert the message to standard OpenAI-compatible message dictionary format."""
        msg: Dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            msg["name"] = self.name
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class AgentResponse(BaseModel):
    """Agent output model after processing a turn."""
    content: str = Field(default="", description="Text response from FRIDAY")
    tool_calls: Optional[List[ToolCall]] = Field(default=None, description="Requested tool calls if any")
    tool_results: Optional[List[ToolResult]] = Field(default=None, description="Results of executed tools if any")
    is_done: bool = Field(default=True, description="Whether the agent turn is complete")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata (timing, token count, etc.)")
