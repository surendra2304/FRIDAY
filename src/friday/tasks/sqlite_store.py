import json
import sqlite3
from datetime import datetime
from pathlib import Path

from friday.core.config import get_settings

from .models import Task, TaskRunLog

DB_PATH = Path(get_settings().memory_db_path)

def _get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = _get_connection()
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

def get_all_tasks() -> list[Task]:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks')
    rows = cur.fetchall()
    conn.close()
    return [_task_from_row(r) for r in rows]

def get_task(task_id: str) -> Task | None:
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    row = cur.fetchone()
    conn.close()
    return _task_from_row(row) if row else None

def save_task(task: Task) -> None:
    conn = _get_connection()
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
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

def log_task_run(log: TaskRunLog) -> None:
    conn = _get_connection()
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
    conn = _get_connection()
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
