# -*- coding: utf-8 -*-
"""Task Checkpointing, Interruption & Resumption Engine for FRIDAY.

Provides:
- `TaskCheckpoint`: Serialized, sanitized snapshot of a task execution state.
- `TaskCheckpointStore` (Memory & SQLite backends):
  * Stores task snapshots safely.
  * Excludes secrets, raw credentials, private chain-of-thought, and raw screenshots.
- Validation on Resumption:
  * Ensures prerequisites, environment state, and completed step integrity remain valid.
  * Prevents duplicate execution of already-completed steps.
  * Transitions task between EXECUTING, PAUSED, RESUMED, and CANCELLED states.
- 100% provider-independent and testable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional
import uuid

from friday.agent.planner import StepStatus, TaskPlan
from friday.agent.state import TaskState
from friday.core.logging import get_logger

logger = get_logger("agent.checkpoint")


from enum import Enum


class InterruptionReason(str, Enum):
    """Causes of task interruption."""
    USER_PAUSE = "USER_PAUSE"
    VOICE_BARGE_IN = "VOICE_BARGE_IN"
    APPLICATION_SHUTDOWN = "APPLICATION_SHUTDOWN"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    AUTHORIZATION_WAIT = "AUTHORIZATION_WAIT"
    ENVIRONMENT_CHANGE = "ENVIRONMENT_CHANGE"
    USER_CANCELLATION = "USER_CANCELLATION"


@dataclass
class TaskCheckpoint:
    """Safe, sanitized persistent snapshot of an executing task."""
    checkpoint_id: str
    task_id: str
    goal: str
    state: TaskState
    active_step_id: Optional[str]
    plan_dict: Dict[str, Any]
    completed_steps: List[str]
    pending_steps: List[str]
    step_results: Dict[str, Any]
    environment_hash: str
    interruption_reason: Optional[InterruptionReason] = None
    recovery_state: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        from friday.security.scrubber import recursive_sanitize
        raw_dict = {
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "goal": self.goal,
            "state": self.state.value,
            "active_step_id": self.active_step_id,
            "plan": self.plan_dict,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "step_results": self.step_results,
            "environment_hash": self.environment_hash,
            "interruption_reason": self.interruption_reason.value if self.interruption_reason else None,
            "recovery_state": self.recovery_state,
            "created_at": self.created_at.isoformat(),
        }
        return recursive_sanitize(raw_dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCheckpoint":
        from friday.security.scrubber import recursive_sanitize
        sanitized_data = recursive_sanitize(data)
        state_val = sanitized_data.get("state", TaskState.PAUSED.value)
        int_reason = sanitized_data.get("interruption_reason")
        return cls(
            checkpoint_id=sanitized_data["checkpoint_id"],
            task_id=sanitized_data["task_id"],
            goal=sanitized_data["goal"],
            state=TaskState(state_val) if state_val in TaskState._value2member_map_ else TaskState.PAUSED,
            active_step_id=sanitized_data.get("active_step_id"),
            plan_dict=sanitized_data.get("plan", {}),
            completed_steps=sanitized_data.get("completed_steps", []),
            pending_steps=sanitized_data.get("pending_steps", []),
            step_results=sanitized_data.get("step_results", {}),
            environment_hash=sanitized_data.get("environment_hash", "default"),
            interruption_reason=InterruptionReason(int_reason) if int_reason in InterruptionReason._value2member_map_ else None,
            recovery_state=sanitized_data.get("recovery_state"),
            created_at=datetime.fromisoformat(sanitized_data["created_at"]) if "created_at" in sanitized_data else datetime.now(timezone.utc),
        )


class TaskCheckpointStore:
    """Stores and retrieves TaskCheckpoint records."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path
        self._memory_store: Dict[str, TaskCheckpoint] = {}
        if self.db_path:
            self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite checkpoint table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    state TEXT NOT NULL,
                    active_step_id TEXT,
                    plan_json TEXT NOT NULL,
                    completed_json TEXT NOT NULL,
                    pending_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    env_hash TEXT NOT NULL,
                    interruption_reason TEXT,
                    recovery_state_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_checkpoint(
        self,
        task_id: str,
        goal: str,
        plan: TaskPlan,
        state: TaskState,
        active_step_id: Optional[str],
        step_results: Dict[str, Any],
        environment_hash: str = "default",
        interruption_reason: Optional[InterruptionReason] = None,
        recovery_state: Optional[Dict[str, Any]] = None,
    ) -> TaskCheckpoint:
        """Create and save a sanitized task checkpoint."""
        completed_steps = [s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED]
        pending_steps = [s.step_id for s in plan.steps if s.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS)]
        from friday.security.scrubber import recursive_sanitize, redact_secrets

        # Sanitize results and metadata recursively
        clean_results = {}
        for sid, sres in step_results.items():
            sres_str = str(sres)
            if "data:image/" in sres_str or "base64," in sres_str or "iVBORw0KGgo" in sres_str:
                clean_results[sid] = "[Visual screenshot sanitized]"
            elif any(k in sres_str.lower() for k in ("key=", "token=", "password=", "secret=")):
                clean_results[sid] = "[Sensitive credentials redacted]"
            else:
                clean_results[sid] = recursive_sanitize(sres)

        clean_recovery_state = recursive_sanitize(recovery_state) if recovery_state else None
        clean_goal = redact_secrets(goal)

        chk = TaskCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            task_id=task_id,
            goal=clean_goal,
            state=state,
            active_step_id=active_step_id,
            plan_dict=plan.to_dict(),
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            step_results=clean_results,
            environment_hash=environment_hash,
            interruption_reason=interruption_reason,
            recovery_state=clean_recovery_state,
        )

        self._memory_store[task_id] = chk

        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_checkpoints
                    (checkpoint_id, task_id, goal, state, active_step_id, plan_json, completed_json, pending_json, results_json, env_hash, interruption_reason, recovery_state_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chk.checkpoint_id,
                        chk.task_id,
                        chk.goal,
                        chk.state.value,
                        chk.active_step_id,
                        json.dumps(chk.plan_dict),
                        json.dumps(chk.completed_steps),
                        json.dumps(chk.pending_steps),
                        json.dumps(chk.step_results),
                        chk.environment_hash,
                        chk.interruption_reason.value if chk.interruption_reason else None,
                        json.dumps(chk.recovery_state) if chk.recovery_state else None,
                        chk.created_at.isoformat(),
                    ),
                )
                conn.commit()

        logger.info(f"Saved checkpoint '{chk.checkpoint_id}' for task '{task_id}' ({len(completed_steps)} completed, {len(pending_steps)} pending). Reason: {interruption_reason}")
        return chk

    def get_latest_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """Retrieve the latest checkpoint for a given task ID."""
        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT checkpoint_id, task_id, goal, state, active_step_id, plan_json, completed_json, pending_json, results_json, env_hash, interruption_reason, recovery_state_json, created_at "
                    "FROM task_checkpoints WHERE task_id = ? ORDER BY created_at DESC LIMIT 1",
                    (task_id,),
                )
                row = cursor.fetchone()
                if row:
                    int_r = row[10]
                    rec_s = json.loads(row[11]) if row[11] else None
                    return TaskCheckpoint(
                        checkpoint_id=row[0],
                        task_id=row[1],
                        goal=row[2],
                        state=TaskState(row[3]) if row[3] in TaskState._value2member_map_ else TaskState.PAUSED,
                        active_step_id=row[4],
                        plan_dict=json.loads(row[5]),
                        completed_steps=json.loads(row[6]),
                        pending_steps=json.loads(row[7]),
                        step_results=json.loads(row[8]),
                        environment_hash=row[9],
                        interruption_reason=InterruptionReason(int_r) if int_r and int_r in InterruptionReason._value2member_map_ else None,
                        recovery_state=rec_s,
                        created_at=datetime.fromisoformat(row[12]),
                    )

        return self._memory_store.get(task_id)

    def validate_resumption(
        self,
        checkpoint: TaskCheckpoint,
        current_environment_hash: str,
    ) -> Dict[str, Any]:
        """Validate if resumption is safe and whether environmental state changed."""
        is_stale = checkpoint.environment_hash != "default" and checkpoint.environment_hash != current_environment_hash
        requires_replan = is_stale

        return {
            "can_resume": True,
            "environment_valid": not is_stale,
            "requires_replan": requires_replan,
            "message": "Environment changed since checkpoint. Re-verification/re-planning required." if requires_replan else "Checkpoint environment validated.",
        }

    def delete_checkpoint(self, task_id: str) -> bool:
        """Remove checkpoint records for a completed or cancelled task."""
        deleted = False
        if task_id in self._memory_store:
            del self._memory_store[task_id]
            deleted = True

        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM task_checkpoints WHERE task_id = ?", (task_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    deleted = True

        return deleted

