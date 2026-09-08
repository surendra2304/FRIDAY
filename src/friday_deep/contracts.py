from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Any, Mapping


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class Trust(str, Enum):
    SYSTEM = "system"
    USER = "user"
    MODEL = "model"
    EXTERNAL = "external"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ToolCapability:
    name: str
    safety: str
    network: bool = False
    filesystem_read: bool = False
    filesystem_write: bool = False
    desktop: bool = False
    credentials: bool = False
    side_effects: bool = False
    allowed_roles: tuple[str, ...] = ()

    def allows_role(self, role: str) -> bool:
        return not self.allowed_roles or role in self.allowed_roles


@dataclass(frozen=True)
class AgentCapability:
    agent_id: str
    role: str
    skills: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    preferred_models: tuple[str, ...] = ()
    max_parallel_tasks: int = 1

    def can_use(self, tool: str) -> bool:
        return not self.allowed_tools or tool in self.allowed_tools


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    title: str
    description: str
    role: str = "general"
    dependencies: tuple[str, ...] = ()
    safety: str = "SAFE"
    tool_name: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PlanEnvelope:
    goal: str
    plan_id: str
    nodes: list[PlanNode]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    task_id: str
    agent_id: str
    status: Status
    output: str = ""
    error_code: str | None = None
    error: str | None = None
    iterations: int = 0
    tool_calls: int = 0
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status is Status.SUCCEEDED
