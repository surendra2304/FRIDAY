"""Persistence for the proactive task scheduler.

Rows live in the ``FRIDAY`` Oracle schema:

* ``scheduled_tasks`` -- task definitions and run counters.
* ``scheduled_task_runs`` -- execution history.

The module keeps stable function names so ``friday.tasks.scheduler`` does not
change. A missing or unusable Oracle DSN raises ``PersistenceConfigError``
through :mod:`friday.core.oracle`; there is no SQLite fallback.
"""

from __future__ import annotations

import json
from datetime import datetime

from friday.core import oracle

from .models import Task, TaskRunLog


def init_db() -> None:
    """Create the scheduler tables. Idempotent."""
    oracle.ensure_schema()


def _task_from_mapping(row: dict) -> Task:
    return Task(
        id=row["id"],
        name=row["name"],
        schedule_type=row["schedule_type"],
        schedule_params=json.loads(row["schedule_params_json"] or "{}"),
        enabled=bool(row["enabled"]),
        safety_level=row["safety_level"],
        max_calls=row["max_calls"],
        retry_limit=row["retry_limit"],
        daily_cap=row["daily_cap"],
        circuit_breaker_threshold=row["circuit_breaker_threshold"],
        run_count=row["run_count"],
        failure_streak=row["failure_streak"],
        last_run=datetime.fromisoformat(row["last_run"]) if row["last_run"] else None,
    )


def get_all_tasks() -> list[Task]:
    rows = oracle.query_all(
        "SELECT id, name, schedule_type, schedule_params_json, enabled, safety_level, "
        "max_calls, retry_limit, daily_cap, circuit_breaker_threshold, run_count, "
        "failure_streak, last_run FROM scheduled_tasks"
    )
    return [_task_from_mapping(r) for r in rows]


def get_task(task_id: str) -> Task | None:
    row = oracle.query_one(
        "SELECT id, name, schedule_type, schedule_params_json, enabled, safety_level, "
        "max_calls, retry_limit, daily_cap, circuit_breaker_threshold, run_count, "
        "failure_streak, last_run FROM scheduled_tasks WHERE id = :id",
        {"id": task_id},
    )
    return _task_from_mapping(row) if row else None


def save_task(task: Task) -> None:
    oracle.execute(
        """
        MERGE INTO scheduled_tasks t
        USING (SELECT :id AS id FROM DUAL) s
        ON (t.id = s.id)
        WHEN MATCHED THEN UPDATE SET
            name = :name,
            schedule_type = :schedule_type,
            schedule_params_json = :schedule_params,
            enabled = :enabled,
            safety_level = :safety_level,
            max_calls = :max_calls,
            retry_limit = :retry_limit,
            daily_cap = :daily_cap,
            circuit_breaker_threshold = :circuit_breaker_threshold,
            run_count = :run_count,
            failure_streak = :failure_streak,
            last_run = :last_run
        WHEN NOT MATCHED THEN INSERT
            (id, name, schedule_type, schedule_params_json, enabled, safety_level,
             max_calls, retry_limit, daily_cap, circuit_breaker_threshold,
             run_count, failure_streak, last_run)
        VALUES
            (:id, :name, :schedule_type, :schedule_params, :enabled, :safety_level,
             :max_calls, :retry_limit, :daily_cap, :circuit_breaker_threshold,
             :run_count, :failure_streak, :last_run)
        """,
        {
            "id": task.id,
            "name": task.name,
            "schedule_type": task.schedule_type.value,
            "schedule_params": json.dumps(task.schedule_params),
            "enabled": int(task.enabled),
            "safety_level": task.safety_level.value,
            "max_calls": task.max_calls,
            "retry_limit": task.retry_limit,
            "daily_cap": task.daily_cap,
            "circuit_breaker_threshold": task.circuit_breaker_threshold,
            "run_count": task.run_count,
            "failure_streak": task.failure_streak,
            "last_run": task.last_run.isoformat() if task.last_run else None,
        },
    )


def delete_task(task_id: str) -> None:
    with oracle.transaction() as conn:
        from sqlalchemy import text as _text

        conn.execute(
            _text("DELETE FROM scheduled_task_runs WHERE task_id = :id"), {"id": task_id}
        )
        conn.execute(_text("DELETE FROM scheduled_tasks WHERE id = :id"), {"id": task_id})


def log_task_run(log: TaskRunLog) -> None:
    oracle.execute(
        "INSERT INTO scheduled_task_runs "
        "(id, task_id, run_time, success, result_json, error, attempt) "
        "VALUES (:id, :task_id, :run_time, :success, :result, :error, :attempt)",
        {
            "id": log.id,
            "task_id": log.task_id,
            "run_time": log.run_time.isoformat(),
            "success": int(log.success),
            "result": json.dumps(log.result) if log.result is not None else None,
            "error": oracle.nullif_empty(log.error),
            "attempt": log.attempt,
        },
    )


def get_task_history(task_id: str) -> list[TaskRunLog]:
    rows = oracle.query_all(
        "SELECT id, task_id, run_time, success, result_json, error, attempt "
        "FROM scheduled_task_runs WHERE task_id = :id ORDER BY run_time DESC",
        {"id": task_id},
    )
    return [
        TaskRunLog(
            id=r["id"],
            task_id=r["task_id"],
            run_time=datetime.fromisoformat(r["run_time"]),
            success=bool(r["success"]),
            result=json.loads(r["result_json"]) if r["result_json"] else None,
            error=r["error"],
            attempt=r["attempt"],
        )
        for r in rows
    ]
