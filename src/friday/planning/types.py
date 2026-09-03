"""Typed Task Model, Statuses, and Task Graph (DAG) for FRIDAY Planning Architecture.

Inspired by Microsoft JARVIS / HuggingGPT:
- Concept of structured subtasks with typed inputs/outputs (TaskDataType)
- Explicit dependency tracking and acyclic graph (DAG) invariants
- Topological wave computation for safe concurrent execution
- Dynamic variable/data passing between upstream and downstream tasks
- Subgraph replacement and resilient state transitions
"""

from __future__ import annotations

import copy
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel

logger = get_logger("planning.types")


class TaskDataType(str, Enum):
    """Data and modality types for subtask inputs and outputs."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    URL = "url"
    JSON = "json"
    STRUCTURED_DATA = "structured_data"
    SCREENSHOT = "screenshot"
    UI_STATE = "ui_state"
    TOOL_RESULT = "tool_result"
    MODEL_RESULT = "model_result"
    ANY = "any"


class TaskStatus(str, Enum):
    """Lifecycle states of a subtask within a TaskGraph."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


@dataclass
class RetryPolicy:
    """Configurable retry policy for resilient subtask execution."""

    max_retries: int = 3
    backoff_factor: float = 1.5
    initial_delay: float = 0.5
    retryable_errors: list[str] = field(
        default_factory=lambda: [
            "timeout",
            "rate_limit",
            "connection_error",
            "503",
            "429",
            "temporary_failure",
        ]
    )

    def is_retryable(self, error_message: str) -> bool:
        if not error_message:
            return False
        err_lower = error_message.lower()
        return any(pattern in err_lower for pattern in self.retryable_errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "backoff_factor": self.backoff_factor,
            "initial_delay": self.initial_delay,
            "retryable_errors": self.retryable_errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryPolicy:
        return cls(
            max_retries=data.get("max_retries", 3),
            backoff_factor=data.get("backoff_factor", 1.5),
            initial_delay=data.get("initial_delay", 0.5),
            retryable_errors=data.get("retryable_errors", ["timeout", "rate_limit"]),
        )


@dataclass
class TaskStep:
    """A discrete, typed, dependency-aware executable subtask."""

    id: str
    description: str
    objective: str = ""
    dependencies: list[str] = field(default_factory=list)
    input_types: list[TaskDataType] = field(default_factory=lambda: [TaskDataType.ANY])
    output_type: TaskDataType = TaskDataType.TEXT
    inputs: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    selected_executor: str | None = None
    selected_model: str | None = None
    tool_name: str | None = None
    fallback_executors: list[str] = field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.SAFE
    requires_confirmation: bool = False
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 1  # 1 = normal, 2 = high, 3 = critical
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    retries_used: int = 0
    timeout_seconds: float = 60.0
    result: Any | None = None
    outputs: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    def is_ready(self, completed_ids: set[str]) -> bool:
        """Check if all prerequisite dependencies have successfully completed."""
        if self.status not in (TaskStatus.PENDING, TaskStatus.READY):
            return False
        return all(dep in completed_ids for dep in self.dependencies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "objective": self.objective,
            "dependencies": self.dependencies,
            "input_types": [t.value for t in self.input_types],
            "output_type": self.output_type.value,
            "inputs": self.inputs,
            "parameters": self.parameters,
            "selected_executor": self.selected_executor,
            "selected_model": self.selected_model,
            "tool_name": self.tool_name,
            "fallback_executors": self.fallback_executors,
            "safety_level": self.safety_level.value,
            "requires_confirmation": self.requires_confirmation,
            "status": self.status.value,
            "priority": self.priority,
            "retry_policy": self.retry_policy.to_dict(),
            "retries_used": self.retries_used,
            "timeout_seconds": self.timeout_seconds,
            "result": self.result,
            "outputs": self.outputs,
            "error": self.error,
            "metadata": self.metadata,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": round(self.duration_seconds, 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskStep:
        input_types = [
            TaskDataType(t) if t in TaskDataType._value2member_map_ else TaskDataType.ANY
            for t in data.get("input_types", ["any"])
        ]
        out_type = data.get("output_type", "text")
        output_type = TaskDataType(out_type) if out_type in TaskDataType._value2member_map_ else TaskDataType.TEXT
        status_val = data.get("status", TaskStatus.PENDING.value)
        status = TaskStatus(status_val) if status_val in TaskStatus._value2member_map_ else TaskStatus.PENDING
        safety_val = data.get("safety_level", SafetyLevel.SAFE.value)
        safety_level = SafetyLevel(safety_val) if safety_val in SafetyLevel._value2member_map_ else SafetyLevel.SAFE

        retry_dict = data.get("retry_policy", {})
        retry_policy = RetryPolicy.from_dict(retry_dict) if retry_dict else RetryPolicy()

        started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None

        return cls(
            id=data["id"],
            description=data.get("description", ""),
            objective=data.get("objective", ""),
            dependencies=data.get("dependencies", []),
            input_types=input_types,
            output_type=output_type,
            inputs=data.get("inputs", {}),
            parameters=data.get("parameters", {}),
            selected_executor=data.get("selected_executor"),
            selected_model=data.get("selected_model"),
            tool_name=data.get("tool_name"),
            fallback_executors=data.get("fallback_executors", []),
            safety_level=safety_level,
            requires_confirmation=data.get("requires_confirmation", False),
            status=status,
            priority=data.get("priority", 1),
            retry_policy=retry_policy,
            retries_used=data.get("retries_used", 0),
            timeout_seconds=data.get("timeout_seconds", 60.0),
            result=data.get("result"),
            outputs=data.get("outputs"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=data.get("duration_seconds", 0.0),
        )


class TaskGraphValidationError(ValueError):
    """Raised when a TaskGraph violates acyclic or structural constraints."""


class TaskGraph:
    """Directed Acyclic Graph (DAG) managing complex task execution workflows."""

    TEMPLATE_PATTERN = re.compile(r"\{\{([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_.-]+))?\}\}")
    TAG_PATTERN = re.compile(r"<([a-zA-Z0-9_-]+)>")

    def __init__(
        self,
        goal: str,
        graph_id: str | None = None,
        tasks: list[TaskStep] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.goal = goal
        self.graph_id = graph_id or f"graph_{uuid.uuid4().hex[:10]}"
        self.tasks: dict[str, TaskStep] = {}
        self.metadata: dict[str, Any] = metadata or {}
        self.created_at = datetime.now(timezone.utc)

        if tasks:
            for task in tasks:
                self.add_task(task)

    def add_task(self, task: TaskStep) -> None:
        if task.id in self.tasks:
            raise TaskGraphValidationError(f"Duplicate task id: '{task.id}' already exists in graph.")
        self.tasks[task.id] = task

    def get_task(self, task_id: str) -> TaskStep | None:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[TaskStep]:
        return list(self.tasks.values())

    def get_completed_ids(self) -> set[str]:
        return {t.id for t in self.tasks.values() if t.status == TaskStatus.COMPLETED}

    def get_ready_tasks(self) -> list[TaskStep]:
        """Return tasks whose dependencies are satisfied and are ready for parallel execution."""
        completed_ids = self.get_completed_ids()
        return [t for t in self.tasks.values() if t.is_ready(completed_ids)]

    def get_dependents(self, task_id: str) -> list[TaskStep]:
        """Return immediate tasks that depend on the given task_id."""
        return [t for t in self.tasks.values() if task_id in t.dependencies]

    def detect_cycles(self) -> list[str] | None:
        """Detect cyclic dependencies in the graph using Kahn's topological sort.

        Returns list of task IDs involved in cycles, or None if acyclic.
        """
        in_degree: dict[str, int] = {t_id: 0 for t_id in self.tasks}
        for task in self.tasks.values():
            for dep in task.dependencies:
                if dep in in_degree:
                    in_degree[task.id] += 1

        queue = [t_id for t_id, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            node = queue.pop(0)
            visited_count += 1
            for task in self.tasks.values():
                if node in task.dependencies:
                    in_degree[task.id] -= 1
                    if in_degree[task.id] == 0:
                        queue.append(task.id)

        if visited_count != len(self.tasks):
            # Nodes with remaining in-degree are in cycle
            return [t_id for t_id, deg in in_degree.items() if deg > 0]
        return None

    def compute_waves(self) -> list[list[TaskStep]]:
        """Compute parallel execution waves/levels in topological order.

        Each wave contains tasks that can execute concurrently.
        """
        cycles = self.detect_cycles()
        if cycles:
            raise TaskGraphValidationError(f"Cyclic dependency detected among tasks: {cycles}")

        completed: set[str] = set()
        remaining = list(self.tasks.values())
        waves: list[list[TaskStep]] = []

        while remaining:
            ready_wave = [t for t in remaining if all(dep in completed for dep in t.dependencies)]
            if not ready_wave:
                unresolved = [t.id for t in remaining]
                raise TaskGraphValidationError(f"Cannot resolve execution waves. Unresolved tasks: {unresolved}")

            waves.append(ready_wave)
            for t in ready_wave:
                completed.add(t.id)
                remaining.remove(t)

        return waves

    def mark_running(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)

    def mark_completed(self, task_id: str, result: Any, outputs: dict[str, Any] | None = None) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.outputs = outputs or {"result": result}
            task.completed_at = datetime.now(timezone.utc)
            if task.started_at:
                task.duration_seconds = (task.completed_at - task.started_at).total_seconds()

    def mark_failed(self, task_id: str, error: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now(timezone.utc)
            if task.started_at:
                task.duration_seconds = (task.completed_at - task.started_at).total_seconds()

    def mark_retrying(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.RETRYING
            task.retries_used += 1

    def mark_skipped(self, task_id: str, reason: str = "") -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.SKIPPED
            task.error = f"Skipped: {reason}" if reason else "Skipped"

    def mark_cancelled(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task:
            task.status = TaskStatus.CANCELLED
            task.error = "Cancelled by user or execution abort"

    def skip_downstream(self, task_id: str, reason: str = "") -> list[str]:
        """Cascade skip to all downstream tasks dependent on a failed task."""
        skipped_ids: list[str] = []
        to_check = [task_id]

        while to_check:
            current_id = to_check.pop(0)
            for t in self.tasks.values():
                if current_id in t.dependencies and t.status in (TaskStatus.PENDING, TaskStatus.READY):
                    t.status = TaskStatus.SKIPPED
                    t.error = f"Prerequisite '{current_id}' failed: {reason}"
                    skipped_ids.append(t.id)
                    to_check.append(t.id)

        return skipped_ids

    def replace_subgraph(self, failed_task_id: str, replacement_tasks: list[TaskStep]) -> None:
        """Replace a failed task and reroute its dependents to the replacement sub-graph."""
        if failed_task_id not in self.tasks:
            raise TaskGraphValidationError(f"Task '{failed_task_id}' does not exist.")

        old_task = self.tasks[failed_task_id]
        dependents = self.get_dependents(failed_task_id)

        # Remove old task
        del self.tasks[failed_task_id]

        # Add replacement tasks
        last_replacement_id = None
        for r_task in replacement_tasks:
            # If replacement task has no dependencies, inherit old task's dependencies
            if not r_task.dependencies:
                r_task.dependencies = list(old_task.dependencies)
            self.add_task(r_task)
            last_replacement_id = r_task.id

        # Point original dependents to the final replacement step
        if last_replacement_id:
            for dep in dependents:
                if failed_task_id in dep.dependencies:
                    dep.dependencies.remove(failed_task_id)
                    dep.dependencies.append(last_replacement_id)

    def resolve_inputs_for_task(self, task_id: str) -> dict[str, Any]:
        """Resolve `<DEP_ID>` or `{{dep_id.key}}` placeholders using outputs of completed tasks."""
        task = self.get_task(task_id)
        if not task:
            return {}

        resolved = copy.deepcopy(task.inputs or task.parameters)

        def _resolve_val(val: Any) -> Any:
            if isinstance(val, str):
                # 1. {{task_id.key}} or {{task_id}}
                t_match = self.TEMPLATE_PATTERN.fullmatch(val.strip())
                if t_match:
                    src_id = t_match.group(1)
                    prop = t_match.group(2)
                    src_task = self.get_task(src_id)
                    if src_task and src_task.status == TaskStatus.COMPLETED:
                        if prop and isinstance(src_task.outputs, dict) and prop in src_task.outputs:
                            return src_task.outputs[prop]
                        return src_task.result
                    return val

                # 2. <TASK_ID> tag style (from Microsoft JARVIS prompt conventions)
                tag_match = self.TAG_PATTERN.fullmatch(val.strip())
                if tag_match:
                    src_id = tag_match.group(1)
                    src_task = self.get_task(src_id)
                    if src_task and src_task.status == TaskStatus.COMPLETED:
                        return src_task.result
                    return val

                # 3. Substring replacement
                def _sub_repl(m: Any) -> str:
                    s_id = m.group(1)
                    s_prop = m.group(2)
                    s_task = self.get_task(s_id)
                    if s_task and s_task.status == TaskStatus.COMPLETED:
                        if s_prop and isinstance(s_task.outputs, dict) and s_prop in s_task.outputs:
                            return str(s_task.outputs[s_prop])
                        return str(s_task.result)
                    return m.group(0)

                return self.TEMPLATE_PATTERN.sub(_sub_repl, val)

            elif isinstance(val, dict):
                return {k: _resolve_val(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_resolve_val(v) for v in val]
            return val

        return {k: _resolve_val(v) for k, v in resolved.items()}

    def is_complete(self) -> bool:
        """Check if all tasks are in a terminal status."""
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}
        return all(t.status in terminal for t in self.tasks.values())

    def is_successful(self) -> bool:
        """Check if workflow completed without critical failures."""
        if not self.is_complete():
            return False
        return all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in self.tasks.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "goal": self.goal,
            "tasks": [t.to_dict() for t in self.tasks.values()],
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "is_complete": self.is_complete(),
            "is_successful": self.is_successful(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskGraph:
        tasks = [TaskStep.from_dict(t) for t in data.get("tasks", [])]
        graph = cls(
            goal=data.get("goal", ""),
            graph_id=data.get("graph_id"),
            tasks=tasks,
            metadata=data.get("metadata", {}),
        )
        if "created_at" in data:
            graph.created_at = datetime.fromisoformat(data["created_at"])
        return graph
