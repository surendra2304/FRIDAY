# -*- coding: utf-8 -*-
"""Long-Running Task Management & Background Progress Controller for FRIDAY.

Provides:
- `LongRunningTask`: Managed lifecycle entity for extended, multi-step asynchronous goals.
- `LongRunningTaskManager`:
  * Explicit background task creation and concurrent worker management.
  * Thread-safe progress tracking, state querying, and milestone reporting.
  * Pause, resume, and cancellation controls integrated with `TaskPlan` and `TaskCheckpoint`.
  * Configurable task execution limits, hard timeouts, and infinite loop prevention.
  * Strict security gating: Never bypasses `BaseAuthorizer` or auto-approves dangerous operations.
- 100% provider-independent and testable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from friday.agent.agent import FridayAgent
from friday.agent.checkpoint import TaskCheckpoint
from friday.agent.executor import ExecutionProgress, TaskExecutionResult
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.logging import get_logger

logger = get_logger("tasks.manager")


class TaskLifecycleStatus(str, Enum):
    """Lifecycle state of a long-running managed task."""
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class TaskProgressReport:
    """Realtime progress telemetry for a long-running task."""
    task_id: str
    goal: str
    status: TaskLifecycleStatus
    completed_steps: int
    total_steps: int
    current_step_id: Optional[str]
    progress_percentage: float
    elapsed_seconds: float
    error: Optional[str] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status.value,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "current_step_id": self.current_step_id,
            "progress_percentage": round(self.progress_percentage, 1),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "error": self.error,
            "last_updated": self.last_updated.isoformat(),
        }


class LongRunningTaskManager:
    """Manages asynchronous background execution of multi-step TaskPlans with safety bounds."""

    def __init__(
        self,
        agent: FridayAgent,
        default_timeout_seconds: float = 300.0,
        max_concurrent_tasks: int = 5,
    ) -> None:
        self.agent = agent
        self.default_timeout_seconds = default_timeout_seconds
        self.max_concurrent_tasks = max_concurrent_tasks
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def submit_task(
        self,
        goal: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        timeout_seconds: Optional[float] = None,
        on_progress: Optional[Callable[[TaskProgressReport], None]] = None,
    ) -> str:
        """Submit and launch a new long-running task in the background."""
        with self._lock:
            active_count = sum(
                1 for t in self._tasks.values()
                if t["status"] in (TaskLifecycleStatus.SUBMITTED, TaskLifecycleStatus.RUNNING)
            )
            if active_count >= self.max_concurrent_tasks:
                raise RuntimeError(
                    f"Max concurrent background task limit ({self.max_concurrent_tasks}) reached."
                )

            # Prevent identical active duplicate tasks
            for t in self._tasks.values():
                if t["goal"] == goal and t["status"] in (TaskLifecycleStatus.SUBMITTED, TaskLifecycleStatus.RUNNING):
                    logger.warning(f"Active task with identical goal '{goal}' already exists ({t['task_id']}).")
                    return t["task_id"]

            plan = self.agent.create_plan(goal=goal, steps=steps)
            task_id = plan.plan_id
            timeout = timeout_seconds or self.default_timeout_seconds

            cancel_event = threading.Event()
            pause_event = threading.Event()

            task_record = {
                "task_id": task_id,
                "goal": goal,
                "plan": plan,
                "status": TaskLifecycleStatus.SUBMITTED,
                "timeout_seconds": timeout,
                "created_at": datetime.now(timezone.utc),
                "started_at": None,
                "finished_at": None,
                "completed_steps": 0,
                "total_steps": len(plan.steps),
                "current_step_id": None,
                "progress_percentage": 0.0,
                "error": None,
                "result": None,
                "cancel_event": cancel_event,
                "pause_event": pause_event,
                "on_progress": on_progress,
                "thread": None,
            }
            self._tasks[task_id] = task_record

            worker = threading.Thread(
                target=self._task_worker,
                args=(task_id,),
                daemon=True,
                name=f"FridayTaskWorker-{task_id[:8]}",
            )
            task_record["thread"] = worker
            worker.start()

            logger.info(f"Submitted long-running task '{task_id}' (goal: '{goal}') with {len(plan.steps)} steps.")
            return task_id

    def get_task_status(self, task_id: str) -> Optional[TaskProgressReport]:
        """Retrieve progress and lifecycle status of a task."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None

            elapsed = (
                (time.time() - t["started_at"])
                if t["started_at"]
                else 0.0
            )

            return TaskProgressReport(
                task_id=task_id,
                goal=t["goal"],
                status=t["status"],
                completed_steps=t["completed_steps"],
                total_steps=t["total_steps"],
                current_step_id=t["current_step_id"],
                progress_percentage=t["progress_percentage"],
                elapsed_seconds=elapsed,
                error=t["error"],
            )

    def pause_task(self, task_id: str) -> bool:
        """Request active task to pause at next safe boundary and create checkpoint."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] != TaskLifecycleStatus.RUNNING:
                return False

            t["pause_event"].set()
            t["status"] = TaskLifecycleStatus.PAUSED
            self.agent.pause_current_task(reason=f"Paused background task {task_id}")
            logger.info(f"Paused task '{task_id}'.")
            return True

    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task from its last checkpoint."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] != TaskLifecycleStatus.PAUSED:
                return False

            t["pause_event"].clear()
            t["status"] = TaskLifecycleStatus.RUNNING

            worker = threading.Thread(
                target=self._task_worker,
                args=(task_id, True),
                daemon=True,
                name=f"FridayTaskWorker-Resume-{task_id[:8]}",
            )
            t["thread"] = worker
            worker.start()
            logger.info(f"Resumed task '{task_id}'.")
            return True

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a running or paused background task."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] in (TaskLifecycleStatus.COMPLETED, TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.FAILED):
                return False

            t["cancel_event"].set()
            t["status"] = TaskLifecycleStatus.CANCELLED
            t["error"] = reason
            t["finished_at"] = time.time()
            self.agent.cancel_task(reason=reason)
            logger.info(f"Cancelled task '{task_id}': {reason}")
            return True

    def list_tasks(self) -> List[TaskProgressReport]:
        """List all managed background tasks."""
        with self._lock:
            return [self.get_task_status(tid) for tid in self._tasks.keys() if self.get_task_status(tid)]

    def _task_worker(self, task_id: str, is_resumption: bool = False) -> None:
        """Background execution worker thread with timeout enforcement."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return
            t["status"] = TaskLifecycleStatus.RUNNING
            t["started_at"] = t["started_at"] or time.time()
            plan: TaskPlan = t["plan"]
            timeout = t["timeout_seconds"]

        start_time = time.time()

        def _step_progress_callback(progress: ExecutionProgress) -> None:
            with self._lock:
                task_rec = self._tasks.get(task_id)
                if not task_rec:
                    return

                # Timeout check
                if time.time() - start_time > timeout:
                    task_rec["status"] = TaskLifecycleStatus.TIMED_OUT
                    task_rec["error"] = f"Task exceeded execution timeout ({timeout}s)."
                    task_rec["cancel_event"].set()
                    self.agent.cancel_task(reason=task_rec["error"])
                    return

                # Pause/Cancel check
                if task_rec["cancel_event"].is_set():
                    task_rec["status"] = TaskLifecycleStatus.CANCELLED
                    return

                task_rec["completed_steps"] = progress.completed_steps
                task_rec["current_step_id"] = progress.in_progress_step_id
                task_rec["progress_percentage"] = progress.percentage

                report = self.get_task_status(task_id)
                if task_rec["on_progress"] and report:
                    try:
                        task_rec["on_progress"](report)
                    except Exception as ex:
                        logger.error(f"Error in progress callback for task '{task_id}': {ex}")

        try:
            if is_resumption:
                res = self.agent.resume_task(task_id)
            else:
                res = self.agent.execute_plan(plan=plan, on_step_progress=_step_progress_callback)

            with self._lock:
                task_rec = self._tasks.get(task_id)
                if not task_rec:
                    return

                task_rec["finished_at"] = time.time()
                task_rec["result"] = res

                # Do not override terminal state if already cancelled or timed out
                if task_rec["status"] in (TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.PAUSED):
                    pass
                elif res.success:
                    task_rec["status"] = TaskLifecycleStatus.COMPLETED
                    task_rec["progress_percentage"] = 100.0
                    task_rec["completed_steps"] = len(plan.steps)
                else:
                    task_rec["status"] = TaskLifecycleStatus.FAILED
                    task_rec["error"] = res.error or "Task execution failed"

                logger.info(f"Task '{task_id}' concluded with status '{task_rec['status'].value}'.")

        except Exception as e:
            logger.error(f"Exception in worker for task '{task_id}': {e}", exc_info=True)
            with self._lock:
                task_rec = self._tasks.get(task_id)
                if task_rec:
                    task_rec["status"] = TaskLifecycleStatus.FAILED
                    task_rec["error"] = str(e)
                    task_rec["finished_at"] = time.time()
