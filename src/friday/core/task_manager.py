"""Asynchronous Task Execution & Cancellation Manager for FRIDAY Central OS.

Provides:
- Non-blocking asynchronous task execution for long-running operations.
- First-class task cancellation and voice-command interruption ('stop', 'cancel that task').
- Global emergency stop integrating subsystem kill switches.
- SSE/WebSocket event streaming and progress telemetry.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Coroutine

from friday.core.logging import get_logger
from friday.core.task_envelope import ActionReceipt, TaskEnvelope, TaskResult, TaskStatus
from friday.ecosystem.emergency_controller import MasterEmergencyController

logger = get_logger("core.task_manager")


class TaskManager:
    """Central manager for async task execution, cancellation, and observable progress."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskEnvelope] = {}
        self._asyncio_tasks: dict[str, asyncio.Task[Any]] = {}
        self._event_queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()
        self.emergency_controller = MasterEmergencyController()

    def get_task(self, task_id: str) -> TaskEnvelope | None:
        """Retrieve task envelope state by task_id."""
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list[TaskEnvelope]:
        """List recent tasks."""
        return list(self._tasks.values())[-limit:]

    async def emit_progress(
        self,
        task_id: str,
        progress: float,
        message: str = "",
        findings: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Update and broadcast task progress to all subscribers."""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.progress = min(max(0.0, progress), 1.0)
        if findings:
            task.findings.extend(findings)
        if artifacts:
            task.artifacts.extend(artifacts)

        event = {
            "type": "progress",
            "task_id": task_id,
            "progress": task.progress,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Fan out to listeners
        queues = self._event_queues.get(task_id, [])
        for q in queues:
            await q.put(event)

    async def submit_async_task(
        self,
        envelope: TaskEnvelope,
        coro_fn: Callable[[TaskEnvelope], Coroutine[Any, Any, TaskResult]],
    ) -> str:
        """Submit a task to execute asynchronously in the background."""
        task_id = envelope.task_id
        envelope.final_state = TaskStatus.RUNNING
        self._tasks[task_id] = envelope
        self._event_queues[task_id] = []

        async def _wrapper() -> None:
            t0 = time.time()
            try:
                res = await coro_fn(envelope)
                envelope.final_state = res.status
                envelope.progress = 1.0
                envelope.artifacts.append(res.result)
                lat = int((time.time() - t0) * 1000)
                receipt = ActionReceipt(
                    requested_action=envelope.action,
                    target=envelope.target_agent,
                    authorization_decision="AUTHORIZED",
                    execution_timestamp=datetime.now(timezone.utc).isoformat(),
                    result=res.result,
                    verification_evidence={"latency_ms": lat, "status": res.status.value},
                    failure_reason=res.error,
                )
                res.receipt = receipt
                await self._notify_completion(task_id, envelope, res)
            except asyncio.CancelledError:
                envelope.final_state = TaskStatus.CANCELLED
                envelope.errors.append({"error": "Task was cancelled by operator or interruption command"})
                await self._notify_cancelled(task_id, envelope)
                logger.info(f"[TaskManager] Task '{task_id}' was CANCELLED.")
                raise
            except Exception as e:
                envelope.final_state = TaskStatus.ERROR
                envelope.errors.append({"error": str(e)})
                res_err = TaskResult(
                    task_id=task_id,
                    target_agent=envelope.target_agent,
                    status=TaskStatus.ERROR,
                    error=str(e),
                )
                await self._notify_completion(task_id, envelope, res_err)
                logger.error(f"[TaskManager] Task '{task_id}' failed: {e}")
            finally:
                self._asyncio_tasks.pop(task_id, None)

        task_handle = asyncio.create_task(_wrapper())
        self._asyncio_tasks[task_id] = task_handle
        return task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task by task_id."""
        task_handle = self._asyncio_tasks.get(task_id)
        if task_handle and not task_handle.done():
            task_handle.cancel()
            if task_id in self._tasks:
                self._tasks[task_id].final_state = TaskStatus.CANCELLED
            return True
        return False

    async def cancel_active_tasks(self) -> int:
        """Cancel all currently running tasks (e.g. from voice command 'stop' or 'cancel that task')."""
        cancelled_count = 0
        for task_id, handle in list(self._asyncio_tasks.items()):
            if not handle.done():
                handle.cancel()
                if task_id in self._tasks:
                    self._tasks[task_id].final_state = TaskStatus.CANCELLED
                cancelled_count += 1
        logger.info(f"[TaskManager] Interruption cancelled {cancelled_count} active task(s).")
        return cancelled_count

    async def emergency_stop(self) -> dict[str, Any]:
        """Execute complete emergency stop: cancel active FRIDAY tasks AND freeze all subsystems."""
        cancelled = await self.cancel_active_tasks()
        # Trigger full cascade
        cascade_report = self.emergency_controller.execute_master_emergency_halt(
            command_phrase="Confirm emergency halt",
            biometric_confidence=1.0,
        )
        return {
            "status": "EMERGENCY_HALT_ACTIVE",
            "cancelled_friday_tasks": cancelled,
            "cascade_report": cascade_report,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def subscribe_events(self, task_id: str) -> AsyncGenerator[str, None]:
        """SSE event generator for real-time task progress streaming."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if task_id not in self._event_queues:
            self._event_queues[task_id] = []
        self._event_queues[task_id].append(q)

        # Initial status event
        task = self._tasks.get(task_id)
        init_state = task.final_state.value if task else "UNKNOWN"
        yield f"event: status\ndata: {{\"task_id\": \"{task_id}\", \"status\": \"{init_state}\"}}\n\n"

        try:
            while True:
                event = await q.get()
                ev_type = event.get("type", "message")
                import json
                yield f"event: {ev_type}\ndata: {json.dumps(event)}\n\n"
                if event.get("type") in ("completion", "cancelled", "error"):
                    break
        finally:
            if task_id in self._event_queues and q in self._event_queues[task_id]:
                self._event_queues[task_id].remove(q)

    async def _notify_completion(self, task_id: str, envelope: TaskEnvelope, result: TaskResult) -> None:
        event = {
            "type": "completion",
            "task_id": task_id,
            "status": result.status.value,
            "summary": result.summary,
            "result": result.result,
            "error": result.error,
        }
        for q in self._event_queues.get(task_id, []):
            await q.put(event)

    async def _notify_cancelled(self, task_id: str, envelope: TaskEnvelope) -> None:
        event = {
            "type": "cancelled",
            "task_id": task_id,
            "status": "CANCELLED",
            "message": "Task cancelled by operator interruption",
        }
        for q in self._event_queues.get(task_id, []):
            await q.put(event)


# Global singleton instance
task_manager = TaskManager()
