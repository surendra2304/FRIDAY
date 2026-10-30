"""Persistence for the proactive task scheduler.

Production rows live in the ``FRIDAY`` Oracle schema:

* ``scheduled_tasks`` -- task definitions and run counters.
* ``scheduled_task_runs`` -- execution history.

The module keeps its historical import path and function names so
``friday.tasks.scheduler`` does not change. SQLite remains reachable for local
development by setting ``FRIDAY_TASKS_SQLITE_PATH`` to a file path; otherwise a
missing Oracle DSN raises ``PersistenceConfigError``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from friday.core import oracle
from friday.core.config import get_settings

from .models import Task, TaskRunLog

#: Historical default. Only used by the SQLite development branch.
DB_PATH = Path(get_settings().memory_db_path)


def _sqlite_path() -> str | None:
    """Return an explicit SQLite path, or None to use Oracle."""
    explicit = os.getenv("FRIDAY_TASKS_SQLITE_PATH", "").strip()
    return explicit or None


def _get_connection(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the scheduler tables. Idempotent on both backends."""
    path = _sqlite_path()
    if not path:
        oracle.ensure_schema()
        return

    conn = _get_connection(path)
    cur = conn.cursor()
    # Tasks table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_params TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            safety_level TEXT NOT NULL,
            max_calls INTEGER,
            retry_limit INTEGER,
            daily_cap INTEGER,
            circuit_breaker_threshold INTEGER,
            run_count INTEGER,
            failure_streak INTEGER,
            last_run TEXT
        )
    ''')
    # Task run log table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS task_run_log (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_time TEXT NOT NULL,
            success INTEGER NOT NULL,
            result TEXT,
            error TEXT,
            attempt INTEGER NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        name=row["name"],
        schedule_type=row["schedule_type"],
        schedule_params=json.loads(row["schedule_params"]),
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
    path = _sqlite_path()
    if not path:
        rows = oracle.query_all(
            "SELECT id, name, schedule_type, schedule_params_json, enabled, safety_level, "
            "max_calls, retry_limit, daily_cap, circuit_breaker_threshold, run_count, "
            "failure_streak, last_run FROM scheduled_tasks"
        )
        return [_task_from_mapping(r) for r in rows]

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks')
    rows = cur.fetchall()
    conn.close()
    return [_task_from_row(r) for r in rows]


def get_task(task_id: str) -> Task | None:
    path = _sqlite_path()
    if not path:
        row = oracle.query_one(
            "SELECT id, name, schedule_type, schedule_params_json, enabled, safety_level, "
            "max_calls, retry_limit, daily_cap, circuit_breaker_threshold, run_count, "
            "failure_streak, last_run FROM scheduled_tasks WHERE id = :id",
            {"id": task_id},
        )
        return _task_from_mapping(row) if row else None

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    row = cur.fetchone()
    conn.close()
    return _task_from_row(row) if row else None


def save_task(task: Task) -> None:
    path = _sqlite_path()
    if not path:
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
        return

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO tasks (
            id, name, schedule_type, schedule_params, enabled, safety_level,
            max_calls, retry_limit, daily_cap, circuit_breaker_threshold,
            run_count, failure_streak, last_run
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        task.id,
        task.name,
        task.schedule_type.value,
        json.dumps(task.schedule_params),
        int(task.enabled),
        task.safety_level.value,
        task.max_calls,
        task.retry_limit,
        task.daily_cap,
        task.circuit_breaker_threshold,
        task.run_count,
        task.failure_streak,
        task.last_run.isoformat() if task.last_run else None,
    ))
    conn.commit()
    conn.close()


def delete_task(task_id: str) -> None:
    path = _sqlite_path()
    if not path:
        with oracle.transaction() as conn:
            from sqlalchemy import text as _text

            conn.execute(
                _text("DELETE FROM scheduled_task_runs WHERE task_id = :id"), {"id": task_id}
            )
            conn.execute(_text("DELETE FROM scheduled_tasks WHERE id = :id"), {"id": task_id})
        return

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()


def log_task_run(log: TaskRunLog) -> None:
    path = _sqlite_path()
    if not path:
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
        return

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO task_run_log (id, task_id, run_time, success, result, error, attempt)
        VALUES (?,?,?,?,?,?,?)
    ''', (
        log.id,
        log.task_id,
        log.run_time.isoformat(),
        int(log.success),
        json.dumps(log.result) if log.result is not None else None,
        log.error,
        log.attempt,
    ))
    conn.commit()
    conn.close()


def get_task_history(task_id: str) -> list[TaskRunLog]:
    path = _sqlite_path()
    if not path:
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

    conn = _get_connection(path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM task_run_log WHERE task_id = ? ORDER BY run_time DESC', (task_id,))
    rows = cur.fetchall()
    conn.close()
    logs: list[TaskRunLog] = []
    for r in rows:
        logs.append(TaskRunLog(
            id=r["id"],
            task_id=r["task_id"],
            run_time=datetime.fromisoformat(r["run_time"]),
            success=bool(r["success"]),
            result=json.loads(r["result"]) if r["result"] else None,
            error=r["error"],
            attempt=r["attempt"],
        ))
    return logs
