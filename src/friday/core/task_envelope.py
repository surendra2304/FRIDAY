"""Universal Task Envelope and Result specification for FRIDAY Universe.

Implements the canonical TaskEnvelope with full audit, authorization, and telemetry fields
mandated by FRIDAY Central OS specification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class ActionReceipt(BaseModel):
    """Structured receipt documenting action execution and verification evidence."""

    requested_action: str
    target: str
    authorization_decision: str = "AUTHORIZED"  # "AUTHORIZED", "REJECTED", "PRE_APPROVED"
    execution_timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: dict[str, Any] = Field(default_factory=dict)
    verification_evidence: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


class TaskEnvelope(BaseModel):
    """Standard inter-agent task dispatch envelope across the FRIDAY Universe."""

    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:8]}")
    parent_task_id: str | None = Field(default=None)
    request_id: str | None = Field(default=None)
    actor: str = Field(default="operator")
    capability: str = Field(default="general")
    objective: str = Field(default="")
    inputs: dict[str, Any] = Field(default_factory=dict)
    trust_level: str = Field(default="operator_confirmed")  # "untrusted", "operator_confirmed", "system_internal"
    authorization_context: dict[str, Any] = Field(default_factory=dict)
    deadline: str | None = Field(default=None)
    idempotency_key: str | None = Field(default=None)
    requested_mode: str = Field(default="sync")  # "sync", "async", "background"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    final_state: TaskStatus = Field(default=TaskStatus.PENDING)

    # Backward compatibility mappings
    source_agent: str = Field(default="friday")
    target_agent: str = Field(default="inference")
    action: str = Field(default="")
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: TaskPriority = Field(default=TaskPriority.NORMAL)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="before")
    @classmethod
    def sync_envelope_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync payload and inputs
            if "payload" in data and "inputs" not in data:
                data["inputs"] = data["payload"]
            elif "inputs" in data and "payload" not in data:
                data["payload"] = data["inputs"]

            # Sync action and objective
            if "action" in data and not data.get("objective"):
                data["objective"] = data["action"]
            elif "objective" in data and not data.get("action"):
                data["action"] = data["objective"]

            # Ensure request_id
            if not data.get("request_id"):
                data["request_id"] = f"req_{uuid.uuid4().hex[:8]}"

            # Ensure idempotency_key
            if not data.get("idempotency_key"):
                data["idempotency_key"] = f"idem_{data.get('task_id', uuid.uuid4().hex[:10])}"

        return data


class TaskResult(BaseModel):
    """Standard inter-agent execution result across the FRIDAY Universe."""

    task_id: str
    target_agent: str
    status: TaskStatus = Field(default=TaskStatus.SUCCESS)
    result: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(default="")
    error: str | None = Field(default=None)
    execution_time_ms: int = Field(default=0)
    completed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    receipt: ActionReceipt | None = Field(default=None)
