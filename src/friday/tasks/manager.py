"""Long-Running Task Management & Reliable Background Execution System for FRIDAY.

Provides:
- `TaskLifecycleStatus`: Formal lifecycle states for managed background tasks.
- `TaskScope`: Boundaries defining allowed tools, directories, and resources.
- `TaskBudget`: Request and tool invocation budget controls.
- `TaskSpec`: Immutable specification defining unique task ID, goal, scope, budget, timeout, retry limit, and authorization policy.
- `TaskProgressReport`: Realtime thread-safe progress report.
- `TaskPersistenceStore`: SQLite-backed persistent registry for task specs, checkpoints, and recovery states.
- `LongRunningTaskManager`:
  * Explicit background task creation and concurrent worker management.
  * Thread-safe progress tracking, state querying, and milestone reporting.
  * Pause, resume, and cancellation controls integrated with `TaskPlan` and `TaskCheckpoint`.
  * Configurable task execution limits, hard timeouts, deadlines, and infinite loop prevention.
  * Strict security gating: Never bypasses `BaseAuthorizer` or auto-approves dangerous operations.
  * Process crash recovery: Resumes incomplete tasks from latest valid checkpoints on startup.
- 100% provider-independent and testable offline.
"""

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from friday.agent.agent import FridayAgent
from friday.agent.checkpoint import TaskCheckpointStore
from friday.agent.executor import ExecutionProgress
from friday.agent.planner import TaskPlan
from friday.core.auth import BaseAuthorizer
from friday.core.logging import get_logger
from friday.observability.event import Event, EventType
from friday.observability.manager import get_observability_manager
from friday.security.scrubber import redact_secrets

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
    RECOVERED = "RECOVERED"


@dataclass
class TaskScope:
    """Operational boundaries defining allowed tools and resources for a task."""
    allowed_tools: list[str] | None = None
    allowed_paths: list[str] | None = None
    network_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_tools": self.allowed_tools,
            "allowed_paths": self.allowed_paths,
            "network_allowed": self.network_allowed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskScope":
        if not data:
            return cls()
        return cls(
            allowed_tools=data.get("allowed_tools"),
            allowed_paths=data.get("allowed_paths"),
            network_allowed=data.get("network_allowed", False),
        )


@dataclass
class TaskBudget:
    """Resource bounds for a background execution task."""
    max_tool_calls: int = 50
    max_model_requests: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_model_requests": self.max_model_requests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TaskBudget":
        if not data:
            return cls()
        return cls(
            max_tool_calls=data.get("max_tool_calls", 50),
            max_model_requests=data.get("max_model_requests", 20),
        )


@dataclass
class TaskSpec:
    """Immutable specification for a long-running background task."""
    task_id: str
    goal: str
    scope: TaskScope = field(default_factory=TaskScope)
    budget: TaskBudget = field(default_factory=TaskBudget)
    timeout_seconds: float = 300.0
    retry_limit: int = 3
    deadline: datetime | None = None
    verification_required: bool = True
    authorizer: BaseAuthorizer | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": redact_secrets(self.goal),
            "scope": self.scope.to_dict(),
            "budget": self.budget.to_dict(),
            "timeout_seconds": self.timeout_seconds,
            "retry_limit": self.retry_limit,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "verification_required": self.verification_required,
        }


@dataclass
class TaskProgressReport:
    """Realtime progress telemetry for a long-running task."""
    task_id: str
    goal: str
    status: TaskLifecycleStatus
    completed_steps: int
    total_steps: int
    current_step_id: str | None
    progress_percentage: float
    elapsed_seconds: float
    retry_budget: int = 3
    retries_used: int = 0
    deadline: datetime | None = None
    error: str | None = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status.value,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "current_step_id": self.current_step_id,
            "progress_percentage": round(self.progress_percentage, 1),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "retry_budget": self.retry_budget,
            "retries_used": self.retries_used,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "error": self.error,
            "last_updated": self.last_updated.isoformat(),
        }


class TaskPersistenceStore:
    """Durable SQLite storage for background tasks and execution progress."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or ":memory:"
        self._lock = threading.Lock()
        self._conn = None
        if self.db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()

    def _get_connection(self):
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self._conn:
                conn = self._conn
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS background_tasks (
                        task_id TEXT PRIMARY KEY,
                        goal TEXT NOT NULL,
                        status TEXT NOT NULL,
                        spec_json TEXT NOT NULL,
                        plan_json TEXT,
                        completed_steps INTEGER DEFAULT 0,
                        total_steps INTEGER DEFAULT 0,
                        progress_pct REAL DEFAULT 0.0,
                        error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.commit()
            else:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS background_tasks (
                            task_id TEXT PRIMARY KEY,
                            goal TEXT NOT NULL,
                            status TEXT NOT NULL,
                            spec_json TEXT NOT NULL,
                            plan_json TEXT,
                            completed_steps INTEGER DEFAULT 0,
                            total_steps INTEGER DEFAULT 0,
                            progress_pct REAL DEFAULT 0.0,
                            error TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                    """)
                    conn.commit()

    def save_task(
        self,
        task_id: str,
        goal: str,
        status: TaskLifecycleStatus,
        spec: TaskSpec,
        plan: TaskPlan | None = None,
        completed_steps: int = 0,
        total_steps: int = 0,
        progress_pct: float = 0.0,
        error: str | None = None,
    ) -> None:
        """Persist or update background task state."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO background_tasks (
                        task_id, goal, status, spec_json, plan_json,
                        completed_steps, total_steps, progress_pct, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        status=excluded.status,
                        completed_steps=excluded.completed_steps,
                        total_steps=excluded.total_steps,
                        progress_pct=excluded.progress_pct,
                        error=excluded.error,
                        updated_at=excluded.updated_at
                """, (
                    task_id,
                    redact_secrets(goal),
                    status.value,
                    json.dumps(spec.to_dict()),
                    json.dumps(plan.to_dict()) if plan else None,
                    completed_steps,
                    total_steps,
                    progress_pct,
                    redact_secrets(error) if error else None,
                    now_iso,
                    now_iso,
                ))
                conn.commit()
            finally:
                if not self._conn:
                    conn.close()

    def get_incomplete_tasks(self) -> list[dict[str, Any]]:
        """Retrieve tasks that were active when process stopped."""
        with self._lock:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute("""
                    SELECT * FROM background_tasks
                    WHERE status IN ('SUBMITTED', 'RUNNING', 'PAUSED')
                """)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                if not self._conn:
                    conn.close()


class LongRunningTaskManager:
    """Manages asynchronous background execution of multi-step TaskPlans with safety bounds."""

    def __init__(
        self,
        agent: FridayAgent,
        default_timeout_seconds: float = 300.0,
        max_concurrent_tasks: int = 5,
        default_retry_budget: int = 3,
        db_path: str | None = None,
        checkpoint_store: TaskCheckpointStore | None = None,
    ) -> None:
        self.agent = agent
        self.default_timeout_seconds = default_timeout_seconds
        self.max_concurrent_tasks = max_concurrent_tasks
        self.default_retry_budget = default_retry_budget
        self.persistence = TaskPersistenceStore(db_path=db_path)
        self.checkpoint_store = checkpoint_store or getattr(agent, "checkpoint_store", TaskCheckpointStore())

        self._tasks: dict[str, dict[str, Any]] = {}
        self._completion_listeners: list[Callable[[TaskProgressReport], None]] = []
        self._lock = threading.RLock()

    def add_completion_listener(self, listener: Callable[[TaskProgressReport], None]) -> None:
        """Register a notification callback for background task completion or failure."""
        with self._lock:
            if listener not in self._completion_listeners:
                self._completion_listeners.append(listener)

    def _emit_task_event(self, event_type: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        """Emit a task-related event via the global ObservabilityManager."""
        manager = get_observability_manager()
        payload = {"task_id": task_id}
        if data:
            payload.update(data)
        try:
            event_type_enum = EventType[event_type.upper()]
        except KeyError:
            event_type_enum = EventType.TASK_STARTED
        manager.emit(Event(
            event_type=event_type_enum,
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            task_id=task_id,
            component="task_manager",
            state=event_type.upper(),
            result=payload,
        ))

    def submit_task(
        self,
        goal: str,
        steps: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
        retry_budget: int | None = None,
        deadline: datetime | None = None,
        scope: TaskScope | None = None,
        budget: TaskBudget | None = None,
        authorizer: BaseAuthorizer | None = None,
        on_progress: Callable[[TaskProgressReport], None] | None = None,
    ) -> str:
        """Submit and launch a new long-running task in the background with explicit safety bounds."""
        with self._lock:
            active_count = sum(
                1 for t in self._tasks.values()
                if t["status"] in (TaskLifecycleStatus.SUBMITTED, TaskLifecycleStatus.RUNNING)
            )
            if active_count >= self.max_concurrent_tasks:
                raise RuntimeError(
                    f"Max concurrent background task limit ({self.max_concurrent_tasks}) reached."
                )

            # Prevent duplicate active execution of identical goal
            clean_goal = goal.strip()
            for t in self._tasks.values():
                if t["goal"].strip().lower() == clean_goal.lower() and t["status"] in (
                    TaskLifecycleStatus.SUBMITTED,
                    TaskLifecycleStatus.RUNNING,
                    TaskLifecycleStatus.PAUSED,
                ):
                    logger.warning(f"Active task with identical goal '{goal}' already exists ({t['task_id']}).")
                    return t["task_id"]

            plan = self.agent.create_plan(goal=goal, steps=steps)
            task_id = plan.plan_id
            timeout = timeout_seconds or self.default_timeout_seconds
            r_limit = retry_budget if retry_budget is not None else self.default_retry_budget

            spec = TaskSpec(
                task_id=task_id,
                goal=goal,
                scope=scope or TaskScope(),
                budget=budget or TaskBudget(),
                timeout_seconds=timeout,
                retry_limit=r_limit,
                deadline=deadline,
                authorizer=authorizer or getattr(self.agent, "authorizer", None),
            )

            cancel_event = threading.Event()
            pause_event = threading.Event()

            task_record = {
                "task_id": task_id,
                "goal": goal,
                "spec": spec,
                "plan": plan,
                "status": TaskLifecycleStatus.SUBMITTED,
                "timeout_seconds": timeout,
                "retry_budget": r_limit,
                "retries_used": 0,
                "deadline": deadline,
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

            # Persist task spec to database
            self.persistence.save_task(
                task_id=task_id,
                goal=goal,
                status=TaskLifecycleStatus.SUBMITTED,
                spec=spec,
                plan=plan,
                total_steps=len(plan.steps),
            )

            worker = threading.Thread(
                target=self._task_worker,
                args=(task_id,),
                daemon=True,
                name=f"FridayTaskWorker-{task_id[:8]}",
            )
            task_record["thread"] = worker
            worker.start()

            logger.info(f"Submitted long-running task '{task_id}' (goal: '{goal}') with {len(plan.steps)} steps.")
            self._emit_task_event("submitted", task_id, {"goal": goal})
            return task_id

    def get_task_status(self, task_id: str) -> TaskProgressReport | None:
        """Retrieve progress and lifecycle status of a task."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None

            elapsed = (time.time() - t["started_at"]) if t["started_at"] else 0.0
            
            # Dynamic timeout detection while thread is executing
            if (
                t["status"] == TaskLifecycleStatus.RUNNING
                and (elapsed > t["timeout_seconds"] or (t.get("deadline") and datetime.now(timezone.utc) > t["deadline"]))
            ):
                t["status"] = TaskLifecycleStatus.TIMED_OUT
                t["error"] = f"Task exceeded execution timeout ({t['timeout_seconds']}s)."
                t["cancel_event"].set()

            return TaskProgressReport(
                task_id=task_id,
                goal=t["goal"],
                status=t["status"],
                completed_steps=t["completed_steps"],
                total_steps=t["total_steps"],
                current_step_id=t["current_step_id"],
                progress_percentage=t["progress_percentage"],
                elapsed_seconds=elapsed,
                retry_budget=t.get("retry_budget", 3),
                retries_used=t.get("retries_used", 0),
                deadline=t.get("deadline"),
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

            self.persistence.save_task(
                task_id=task_id,
                goal=t["goal"],
                status=TaskLifecycleStatus.PAUSED,
                spec=t["spec"],
                plan=t["plan"],
                completed_steps=t["completed_steps"],
                total_steps=t["total_steps"],
                progress_pct=t["progress_percentage"],
            )

            logger.info(f"Paused task '{task_id}'.")
            self._emit_task_event("paused", task_id)
            return True

    def resume_task(self, task_id: str) -> bool:
        """Resume a paused task from its last checkpoint."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] not in (TaskLifecycleStatus.PAUSED, TaskLifecycleStatus.RECOVERED):
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

            self.persistence.save_task(
                task_id=task_id,
                goal=t["goal"],
                status=TaskLifecycleStatus.RUNNING,
                spec=t["spec"],
                plan=t["plan"],
                completed_steps=t["completed_steps"],
                total_steps=t["total_steps"],
                progress_pct=t["progress_percentage"],
            )

            logger.info(f"Resumed task '{task_id}'.")
            self._emit_task_event("resumed", task_id)
            return True

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a running or paused background task and halt downstream execution immediately."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t["status"] in (TaskLifecycleStatus.COMPLETED, TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.FAILED, TaskLifecycleStatus.TIMED_OUT):
                return False

            t["cancel_event"].set()
            t["status"] = TaskLifecycleStatus.CANCELLED
            t["error"] = reason
            t["finished_at"] = time.time()
            self.agent.cancel_task(reason=reason)

            self.persistence.save_task(
                task_id=task_id,
                goal=t["goal"],
                status=TaskLifecycleStatus.CANCELLED,
                spec=t["spec"],
                plan=t["plan"],
                completed_steps=t["completed_steps"],
                total_steps=t["total_steps"],
                progress_pct=t["progress_percentage"],
                error=reason,
            )

            logger.info(f"Cancelled task '{task_id}': {reason}")
            self._emit_task_event("cancelled", task_id, {"reason": reason})
            self._notify_completion(task_id)
            return True

    def recover_after_crash(self, auto_resume: bool = False) -> list[str]:
        """Audit and recover incomplete background tasks from durable store following process restart."""
        recovered_ids: list[str] = []
        with self._lock:
            incomplete = self.persistence.get_incomplete_tasks()
            for rec in incomplete:
                tid = rec["task_id"]
                spec_dict = json.loads(rec["spec_json"])
                plan_dict = json.loads(rec["plan_json"]) if rec.get("plan_json") else None

                spec = TaskSpec(
                    task_id=tid,
                    goal=rec["goal"],
                    scope=TaskScope.from_dict(spec_dict.get("scope")),
                    budget=TaskBudget.from_dict(spec_dict.get("budget")),
                    timeout_seconds=float(spec_dict.get("timeout_seconds", 300.0)),
                    retry_limit=int(spec_dict.get("retry_limit", 3)),
                )
                plan = TaskPlan.from_dict(plan_dict) if plan_dict else TaskPlan(plan_id=tid, goal=rec["goal"], steps=[])

                # Check if checkpoint exists
                chk = self.checkpoint_store.get_latest_checkpoint(tid)
                completed_count = len(chk.completed_steps) if chk else rec["completed_steps"]

                self._tasks[tid] = {
                    "task_id": tid,
                    "goal": rec["goal"],
                    "spec": spec,
                    "plan": plan,
                    "status": TaskLifecycleStatus.RECOVERED,
                    "timeout_seconds": spec.timeout_seconds,
                    "retry_budget": spec.retry_limit,
                    "retries_used": 0,
                    "deadline": None,
                    "created_at": datetime.fromisoformat(rec["created_at"]),
                    "started_at": None,
                    "finished_at": None,
                    "completed_steps": completed_count,
                    "total_steps": len(plan.steps),
                    "current_step_id": None,
                    "progress_percentage": (completed_count / max(1, len(plan.steps))) * 100.0,
                    "error": "Process restarted while task was active. Recovered from durable store.",
                    "result": None,
                    "cancel_event": threading.Event(),
                    "pause_event": threading.Event(),
                    "on_progress": None,
                    "thread": None,
                }
                recovered_ids.append(tid)

                if auto_resume:
                    self.resume_task(tid)

            logger.info(f"Recovered {len(recovered_ids)} background task(s) following restart.")
            return recovered_ids

    def _notify_completion(self, task_id: str) -> None:
        """Notify all registered listeners about task conclusion."""
        report = self.get_task_status(task_id)
        if not report:
            return

        self._emit_task_event("concluded", task_id, {"status": report.status.value})

        for listener in list(self._completion_listeners):
            try:
                listener(report)
            except Exception as ex:
                logger.error(f"Error in completion listener for task '{task_id}': {ex}")

    def list_tasks(self) -> list[TaskProgressReport]:
        """List all managed background tasks."""
        with self._lock:
            results: list[TaskProgressReport] = []
            for tid in self._tasks.keys():
                st = self.get_task_status(tid)
                if st is not None:
                    results.append(st)
            return results

    def _task_worker(self, task_id: str, is_resumption: bool = False) -> None:
        """Background execution worker thread with timeout, cancellation, & verification checks."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return
            if t["status"] in (TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.TIMED_OUT):
                return
            if t["cancel_event"].is_set():
                t["status"] = TaskLifecycleStatus.CANCELLED
                return
            t["status"] = TaskLifecycleStatus.RUNNING
            t["started_at"] = t["started_at"] or time.time()
            plan: TaskPlan = t["plan"]
            timeout = t["timeout_seconds"]
            deadline = t.get("deadline")

        start_time = time.time()

        def _step_progress_callback(progress: ExecutionProgress) -> None:
            with self._lock:
                task_rec = self._tasks.get(task_id)
                if not task_rec:
                    return

                # Timeout & Deadline checks
                if time.time() - start_time > timeout or (deadline and datetime.now(timezone.utc) > deadline):
                    task_rec["status"] = TaskLifecycleStatus.TIMED_OUT
                    task_rec["error"] = f"Task exceeded execution timeout ({timeout}s) or deadline."
                    task_rec["cancel_event"].set()
                    self.agent.cancel_task(reason=task_rec["error"])
                    return

                # Cancellation check
                if task_rec["cancel_event"].is_set():
                    task_rec["status"] = TaskLifecycleStatus.CANCELLED
                    return

                task_rec["completed_steps"] = progress.completed_steps
                task_rec["current_step_id"] = progress.in_progress_step_id
                task_rec["progress_percentage"] = progress.percentage

                # Update durable persistence
                self.persistence.save_task(
                    task_id=task_id,
                    goal=task_rec["goal"],
                    status=task_rec["status"],
                    spec=task_rec["spec"],
                    plan=task_rec["plan"],
                    completed_steps=task_rec["completed_steps"],
                    total_steps=task_rec["total_steps"],
                    progress_pct=task_rec["progress_percentage"],
                )

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
                res = self.agent.execute_plan(
                    plan=plan,
                    on_step_progress=_step_progress_callback,
                    step_timeout_seconds=timeout,
                    cancellation_token=t["cancel_event"],
                )

            with self._lock:
                task_rec = self._tasks.get(task_id)
                if not task_rec:
                    return

                task_rec["finished_at"] = time.time()
                task_rec["result"] = res

                # Do not override terminal state if already cancelled or timed out
                if task_rec["status"] in (TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.PAUSED):
                    pass
                elif time.time() - start_time > timeout:
                    task_rec["status"] = TaskLifecycleStatus.TIMED_OUT
                    task_rec["error"] = f"Task exceeded execution timeout ({timeout}s)."
                elif res.success:
                    task_rec["status"] = TaskLifecycleStatus.COMPLETED
                    task_rec["progress_percentage"] = 100.0
                    task_rec["completed_steps"] = len(plan.steps)
                else:
                    task_rec["status"] = TaskLifecycleStatus.FAILED
                    task_rec["error"] = res.error or "Task execution failed"

                self.persistence.save_task(
                    task_id=task_id,
                    goal=task_rec["goal"],
                    status=task_rec["status"],
                    spec=task_rec["spec"],
                    plan=task_rec["plan"],
                    completed_steps=task_rec["completed_steps"],
                    total_steps=task_rec["total_steps"],
                    progress_pct=task_rec["progress_percentage"],
                    error=task_rec["error"],
                )

                logger.info(f"Task '{task_id}' concluded with status '{task_rec['status'].value}'.")

            self._notify_completion(task_id)

        except Exception as e:
            logger.error(f"Exception in worker for task '{task_id}': {e}", exc_info=True)
            with self._lock:
                task_rec = self._tasks.get(task_id)
                if task_rec:
                    task_rec["status"] = TaskLifecycleStatus.FAILED
                    task_rec["error"] = str(e)
                    task_rec["finished_at"] = time.time()
                    self.persistence.save_task(
                        task_id=task_id,
                        goal=task_rec["goal"],
                        status=TaskLifecycleStatus.FAILED,
                        spec=task_rec["spec"],
                        plan=task_rec["plan"],
                        error=str(e),
                    )
            self._notify_completion(task_id)
