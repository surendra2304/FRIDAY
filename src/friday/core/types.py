"""Core type definitions and data models for FRIDAY."""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Role(str, Enum):
    """Message role definitions."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TrustLevel(str, Enum):
    """Provenance and trust boundary classification for memory and content."""
    TRUSTED_USER = "trusted_user"          # Direct user commands & explicit preferences
    SYSTEM_INSTRUCTION = "system_instruction" # Built-in system prompt & policies
    MODEL_OUTPUT = "model_output"          # AI responses & synthesized plans
    UNTRUSTED_EXTERNAL = "untrusted_external" # Screen OCR, websites, tool output, file data


class ReleaseStatus(str, Enum):
    """Honest engineering release readiness status definitions.
    
    A blocked hardware or external dependency strictly prevents REAL_WORLD_VERIFIED.
    """
    SOFTWARE_VERIFIED = "SOFTWARE_VERIFIED"      # 100% software test suite passes offline
    REAL_WORLD_VERIFIED = "REAL_WORLD_VERIFIED"  # All real hardware and cloud services verified
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"        # Mandatory real capability is blocked externally
    NOT_TESTED = "NOT_TESTED"                    # Capability unverified
    FAILED = "FAILED"                            # Invariant violation or defect detected
    PARTIAL = "PARTIAL"                          # Mixed verification state


class SafetyLevel(str, Enum):
    """Tool safety classification levels.

    SAFE:
        Read-only, non-destructive, non-disclosive operations.
        Can execute automatically.

    SENSITIVE:
        Modifies user preferences, application settings, files.
        Requires explicit user confirmation.

    DANGEROUS:
        System commands, database deletions, network connections,
        actions modifying security controls.
        Requires explicit authorization capability.
    """
    SAFE = "SAFE"
    SENSITIVE = "SENSITIVE"
    DANGEROUS = "DANGEROUS"


class ToolCall(BaseModel):
    """Representation of a function call requested by a language model."""
    id: str = Field(default="", description="Unique identifier for the tool call")
    name: str = Field(..., description="Name of the tool to execute")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments passed to the tool")
    thought_signature: Any | None = Field(default=None, description="Cryptographic thought signature from thinking models")


class ToolResult(BaseModel):
    """Result of a tool execution."""
    tool_call_id: str = Field(default="", description="Identifier of the matching tool call")
    name: str = Field(..., description="Name of the executed tool")
    content: str = Field(..., description="Textual or JSON output of the execution")
    is_error: bool = Field(default=False, description="Whether the tool execution encountered an error")
    safety_level: SafetyLevel = Field(default=SafetyLevel.SAFE, description="Safety tier of the tool")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Optional metadata for tool execution")

    @field_validator("content", mode="after")
    @classmethod
    def sanitize_content(cls, val: str) -> str:
        from friday.security.scrubber import redact_secrets
        return redact_secrets(val)


class Message(BaseModel):
    """Standard conversational message model."""
    role: Role = Field(..., description="Role of the message sender")
    content: str = Field(default="", description="Text content of the message")
    name: str | None = Field(default=None, description="Optional author or tool name")
    tool_calls: list[ToolCall] | None = Field(default=None, description="Tool calls requested by assistant")
    tool_call_id: str | None = Field(default=None, description="ID of the tool call this message responds to")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    trust_level: TrustLevel = Field(default=TrustLevel.TRUSTED_USER, description="Trust boundary classification")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary provenance and classification metadata")

    @field_validator("content", mode="after")
    @classmethod
    def sanitize_message_content(cls, val: str) -> str:
        from friday.security.scrubber import redact_secrets
        return redact_secrets(val)

    def to_provider_dict(self) -> dict[str, Any]:
        """Convert the message to standard OpenAI-compatible message dictionary format."""
        msg: dict[str, Any] = {"role": self.role.value, "content": self.content}
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
    tool_calls: list[ToolCall] | None = Field(default=None, description="Requested tool calls if any")
    tool_results: list[ToolResult] | None = Field(default=None, description="Results of executed tools if any")
    is_done: bool = Field(default=True, description="Whether the agent turn is complete")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Execution metadata (timing, token count, etc.)")


class AuthorizationDecision(str, Enum):
    """Possible outcomes of an authorization request."""
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AuthorizationRequest(BaseModel):
    """A formal request to authorize a tool call execution."""
    tool_name: str = Field(..., description="Name of the tool requested")
    safety_level: SafetyLevel = Field(..., description="Safety level classification of the tool")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments passed to the tool")
    tool_call_id: str | None = Field(default="", description="Associated tool call identifier")
    purpose: str | None = Field(default=None, description="Implicit or explicit purpose of the execution")
    affected_resource: str | None = Field(default=None, description="Identifier of the resource affected (e.g. file path)")


class AuthorizationResponse(BaseModel):
    """Decision outcome and reason for a tool call authorization request."""
    decision: AuthorizationDecision = Field(..., description="The authorization decision")
    reason: str | None = Field(default=None, description="Detailed rationale for the decision")
    capability: Any | None = Field(default=None, description="Cryptographic authorization token granting single-use execution rights")


class MemorySearchResult(BaseModel):
    """Result of a historical memory search."""
    conversation_id: str = Field(..., description="ID of the conversation containing the message")
    conversation_title: str = Field(default="", description="Title of the conversation")
    message_id: str = Field(..., description="Unique message ID")
    role: Role = Field(..., description="Message author role")
    content: str = Field(..., description="Text content of the matching message")
    timestamp: datetime = Field(..., description="Timestamp of the message")
    score: float = Field(default=1.0, description="Relevance ranking score")
    trust_level: TrustLevel = Field(default=TrustLevel.TRUSTED_USER, description="Trust level classification")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Provenance metadata")


class EmbeddingRecord(BaseModel):
    """Durable representation of a semantic embedding vector and source reference."""
    id: str = Field(..., description="Unique ID of the embedding record")
    conversation_id: str = Field(..., description="Conversation ID reference")
    message_id: str | None = Field(default=None, description="Optional Message ID reference")
    source_text: str = Field(..., description="Source text that was embedded")
    embedding: list[float] = Field(..., description="Dense embedding vector array")
    model: str = Field(..., description="Identifier of the model that generated the embedding")
    dimension: int = Field(..., description="Dimensionality of the embedding vector")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Creation timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata attributes")


class SemanticSearchResult(BaseModel):
    """Result of a semantic vector similarity search."""
    record_id: str = Field(..., description="Unique ID of the matching embedding record")
    conversation_id: str = Field(..., description="Conversation ID reference")
    message_id: str | None = Field(default=None, description="Optional Message ID reference")
    source_text: str = Field(..., description="Text content of the retrieved memory")
    score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")
    created_at: datetime = Field(..., description="Timestamp when the embedding was created")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the embedding")
