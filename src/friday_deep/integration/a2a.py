from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class State(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class AgentCard:
    agent_id: str
    name: str
    description: str
    version: str
    skills: tuple[str, ...]
    capabilities: tuple[str, ...]
    url: str


@dataclass
class Task:
    task_id: str
    session_id: str
    skill: str
    input_text: str
    state: State = State.SUBMITTED
    deadline: datetime | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Result:
    task_id: str
    state: State
    output: str = ""
    artifacts: list[dict] = field(default_factory=list)
    error: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def dict(self):
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "output": self.output,
            "artifacts": self.artifacts,
            "error": self.error,
            "completed_at": self.completed_at.isoformat(),
        }
