"""Task & Todo Management Tool for FRIDAY.

Provides persistent task creation, listing, completion, and updating
using SQLite persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.persistence.task_store import SQLiteTaskStore
from friday.tools.base import BaseTool

logger = get_logger("tools.task_management")


class ManageTasksTool(BaseTool):
    """Manage persistent tasks, todos, and reminders."""

    name = "manage_tasks"
    description = (
        "Create, view, complete, or update persistent tasks and todo items. "
        "Actions: 'create', 'list', 'complete', 'delete', 'update'."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "complete", "delete", "update"],
                "description": "Task operation to perform.",
            },
            "title": {
                "type": "string",
                "description": "Task title or description when creating or updating.",
            },
            "task_id": {
                "type": "string",
                "description": "Unique task ID or title keyword when completing, updating, or deleting.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high", "urgent"],
                "description": "Priority level of the task (default: 'medium').",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled"],
                "description": "Filter status when listing, or target status when updating.",
            },
            "due_date": {
                "type": "string",
                "description": "Optional ISO due date/time string (e.g. '2026-09-04 10:00').",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: SQLiteTaskStore | None = None) -> None:
        super().__init__()
        self._store = store

    def _get_store(self) -> SQLiteTaskStore:
        if self._store is None:
            self._store = SQLiteTaskStore()
        return self._store

    def execute(
        self,
        action: str,
        title: str | None = None,
        task_id: str | None = None,
        priority: str = "medium",
        status: str | None = None,
        due_date: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        store = self._get_store()
        act = (action or "").lower().strip()

        # Parse due date if provided
        due_timestamp = None
        if due_date:
            try:
                dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                due_timestamp = dt.timestamp()
            except Exception:
                due_timestamp = None

        if act == "create":
            if not title:
                return ToolResult(
                    name=self.name,
                    content="Error: 'title' is required to create a new task.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            item = store.create_task(
                title=title,
                priority=priority or "medium",
                due_at=due_timestamp,
            )
            return ToolResult(
                name=self.name,
                content=f"Task created successfully: [{item.id}] '{item.title}' (Priority: {item.priority.upper()})",
                is_error=False,
                safety_level=self.safety_level,
            )

        elif act == "list":
            tasks = store.list_tasks(status=status, priority=priority if priority != "medium" else None)
            if not tasks:
                filt_str = f" with status '{status}'" if status else ""
                return ToolResult(
                    name=self.name,
                    content=f"You have no tasks recorded{filt_str}.",
                    is_error=False,
                    safety_level=self.safety_level,
                )

            lines = [f"Found {len(tasks)} task{'s' if len(tasks) != 1 else ''}:"]
            for i, t in enumerate(tasks, 1):
                status_icon = "✓" if t.status == "completed" else "○"
                due_str = f" (Due: {datetime.fromtimestamp(t.due_at).strftime('%Y-%m-%d %H:%M')})" if t.due_at else ""
                lines.append(f"{i}. {status_icon} [{t.id}] {t.title} — {t.priority.upper()} ({t.status}){due_str}")

            return ToolResult(
                name=self.name,
                content="\n".join(lines),
                is_error=False,
                safety_level=self.safety_level,
            )

        elif act == "complete":
            target = task_id or title
            if not target:
                return ToolResult(
                    name=self.name,
                    content="Error: 'task_id' or 'title' required to mark a task complete.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            completed = store.complete_task(target)
            if completed:
                return ToolResult(
                    name=self.name,
                    content=f"Task marked complete: [{completed.id}] '{completed.title}'.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return ToolResult(
                name=self.name,
                content=f"Task '{target}' not found or already completed.",
                is_error=True,
                safety_level=self.safety_level,
            )

        elif act == "delete":
            if not task_id:
                return ToolResult(
                    name=self.name,
                    content="Error: 'task_id' required to delete a task.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            ok = store.delete_task(task_id)
            if ok:
                return ToolResult(
                    name=self.name,
                    content=f"Task '{task_id}' deleted.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return ToolResult(
                name=self.name,
                content=f"Task '{task_id}' not found.",
                is_error=True,
                safety_level=self.safety_level,
            )

        elif act == "update":
            if not task_id:
                return ToolResult(
                    name=self.name,
                    content="Error: 'task_id' required to update a task.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            updated = store.update_task(
                task_id=task_id,
                title=title,
                status=status,
                priority=priority if priority != "medium" else None,
                due_at=due_timestamp,
            )
            if updated:
                return ToolResult(
                    name=self.name,
                    content=f"Task '{task_id}' updated successfully.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return ToolResult(
                name=self.name,
                content=f"Task '{task_id}' not found.",
                is_error=True,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Unknown action '{action}'. Supported actions: create, list, complete, delete, update.",
            is_error=True,
            safety_level=self.safety_level,
        )
