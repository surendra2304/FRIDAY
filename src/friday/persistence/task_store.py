"""Persistent task store for user todos, reminders, and scheduled tasks.

Two backends share one interface:

* :class:`OracleTaskStore` -- the production store, writing to the ``FRIDAY``
  Oracle schema (``user_tasks``) through :mod:`friday.core.oracle`.
* :class:`SQLiteTaskStore` -- test-only, reachable only when a test passes an
  explicit ``db_path`` to :func:`create_task_store`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from friday.core import oracle
from friday.core.logging import get_logger

logger = get_logger("persistence.task_store")

DEFAULT_DB_PATH = "data/friday.db"

_TASK_COLUMNS = (
    "id, title, description, status, priority, created_at, due_at, "
    "completed_at, recurrence, metadata_json"
)

_TASK_ORDERING = (
    " ORDER BY CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END, "
    "created_at DESC"
)


@dataclass
class TaskItem:
    """Represents a persistent user task or todo item."""

    id: str
    title: str
    description: str = ""
    status: str = "pending"  # "pending", "in_progress", "completed", "cancelled"
    priority: str = "medium"  # "low", "medium", "high", "urgent"
    created_at: float = field(default_factory=time.time)
    due_at: float | None = None
    completed_at: float | None = None
    recurrence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TaskItem:
        meta = {}
        if row[9]:
            try:
                meta = json.loads(row[9])
            except Exception:
                meta = {}
        return cls(
            id=row[0],
            title=row[1],
            description=row[2] or "",
            status=row[3] or "pending",
            priority=row[4] or "medium",
            created_at=row[5] or time.time(),
            due_at=row[6],
            completed_at=row[7],
            recurrence=row[8],
            metadata=meta,
        )

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> TaskItem:
        """Build from a lower-cased Oracle row mapping."""
        raw_meta = row.get("metadata_json")
        meta: dict[str, Any] = {}
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except Exception:
                meta = {}
        return cls(
            id=row["id"],
            title=row["title"],
            description=row.get("description") or "",
            status=row.get("status") or "pending",
            priority=row.get("priority") or "medium",
            created_at=row.get("created_at") or time.time(),
            due_at=row.get("due_at"),
            completed_at=row.get("completed_at"),
            recurrence=row.get("recurrence"),
            metadata=meta,
        )


class SQLiteTaskStore:
    """Test-only task store backed by an explicit SQLite path.

    Production code must use :class:`OracleTaskStore` through
    :func:`create_task_store`; constructing this class outside a pytest run
    raises :class:`~friday.core.exceptions.PersistenceConfigError`.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        from friday.core.exceptions import PersistenceConfigError
        from friday.core.oracle import ephemeral_backend_allowed

        if not ephemeral_backend_allowed():
            raise PersistenceConfigError(
                "SQLiteTaskStore is test-only. Use create_task_store() so FRIDAY "
                "persists user tasks to Oracle Autonomous Database."
            )
        self.db_path = db_path
        self._lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    priority TEXT DEFAULT 'medium',
                    created_at REAL NOT NULL,
                    due_at REAL,
                    completed_at REAL,
                    recurrence TEXT,
                    metadata_json TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON user_tasks(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON user_tasks(priority);")
            conn.commit()

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_at: float | None = None,
        recurrence: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskItem:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        now = time.time()
        meta_json = json.dumps(metadata or {})

        item = TaskItem(
            id=task_id,
            title=title.strip(),
            description=description.strip(),
            status="pending",
            priority=priority.lower().strip() or "medium",
            created_at=now,
            due_at=due_at,
            completed_at=None,
            recurrence=recurrence,
            metadata=metadata or {},
        )

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_tasks (
                    id, title, description, status, priority, created_at, due_at, completed_at, recurrence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.id,
                    item.title,
                    item.description,
                    item.status,
                    item.priority,
                    item.created_at,
                    item.due_at,
                    item.completed_at,
                    item.recurrence,
                    meta_json,
                ),
            )
            conn.commit()

        logger.info(f"Created task '{item.title}' (ID: {item.id})")
        return item

    def list_tasks(
        self,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[TaskItem]:
        query = "SELECT id, title, description, status, priority, created_at, due_at, completed_at, recurrence, metadata_json FROM user_tasks"
        params: list[Any] = []
        clauses: list[str] = []

        if status:
            clauses.append("status = ?")
            params.append(status.lower().strip())
        if priority:
            clauses.append("priority = ?")
            params.append(priority.lower().strip())

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY CASE status WHEN 'pending' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END, created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [TaskItem.from_row(r) for r in rows]

    def get_task(self, task_id: str) -> TaskItem | None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, title, description, status, priority, created_at, due_at, completed_at, recurrence, metadata_json FROM user_tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()
            return TaskItem.from_row(row) if row else None

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        due_at: float | None = None,
    ) -> TaskItem | None:
        item = self.get_task(task_id)
        if not item:
            return None

        if title is not None:
            item.title = title.strip()
        if description is not None:
            item.description = description.strip()
        if status is not None:
            item.status = status.lower().strip()
            if item.status == "completed" and not item.completed_at:
                item.completed_at = time.time()
        if priority is not None:
            item.priority = priority.lower().strip()
        if due_at is not None:
            item.due_at = due_at

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE user_tasks
                SET title = ?, description = ?, status = ?, priority = ?, due_at = ?, completed_at = ?
                WHERE id = ?;
                """,
                (item.title, item.description, item.status, item.priority, item.due_at, item.completed_at, item.id),
            )
            conn.commit()

        return item

    def complete_task(self, task_id_or_keyword: str) -> TaskItem | None:
        target = task_id_or_keyword.strip()
        item = self.get_task(target)
        if not item:
            # Try searching by title keyword
            with self._lock, self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT id FROM user_tasks WHERE status != 'completed' AND LOWER(title) LIKE ? LIMIT 1",
                    (f"%{target.lower()}%",),
                )
                row = cursor.fetchone()
                if row:
                    item = self.get_task(row[0])

        if item:
            return self.update_task(item.id, status="completed")
        return None

    def delete_task(self, task_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM user_tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0


class OracleTaskStore:
    """Thread-safe task store backed by Oracle Autonomous Database."""

    backend = "oracle"

    def __init__(self, dsn: str | None = None, *, engine: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._dsn = dsn
        self._engine = engine

    @property
    def engine(self) -> Any:
        """Resolve the shared Oracle engine on first use (never at import)."""
        if self._engine is None:
            self._engine = oracle.get_engine(self._dsn)
        return self._engine

    @property
    def db_path(self) -> str:
        """Compatibility accessor; Oracle has no file path."""
        return "oracle://FRIDAY"

    def _query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return oracle.query_all(sql, params, engine=self.engine)

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_at: float | None = None,
        recurrence: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskItem:
        item = TaskItem(
            id=f"task_{uuid.uuid4().hex[:8]}",
            title=title.strip(),
            description=description.strip(),
            status="pending",
            priority=priority.lower().strip() or "medium",
            created_at=time.time(),
            due_at=due_at,
            completed_at=None,
            recurrence=recurrence,
            metadata=metadata or {},
        )
        with self._lock:
            oracle.execute(
                "INSERT INTO user_tasks (id, title, description, status, priority, "
                "created_at, due_at, completed_at, recurrence, metadata_json) "
                "VALUES (:id, :title, :description, :status, :priority, :created_at, "
                ":due_at, :completed_at, :recurrence, :metadata_json)",
                {
                    "id": item.id,
                    "title": item.title,
                    "description": oracle.nullif_empty(item.description),
                    "status": item.status,
                    "priority": item.priority,
                    "created_at": float(item.created_at),
                    "due_at": item.due_at,
                    "completed_at": item.completed_at,
                    "recurrence": oracle.nullif_empty(item.recurrence),
                    "metadata_json": json.dumps(item.metadata),
                },
                engine=self.engine,
            )
        logger.info("Created task '%s' (ID: %s)", item.title, item.id)
        return item

    def list_tasks(
        self,
        status: str | None = None,
        priority: str | None = None,
        limit: int = 50,
    ) -> list[TaskItem]:
        query = f"SELECT {_TASK_COLUMNS} FROM user_tasks"
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if status:
            clauses.append("status = :status")
            params["status"] = status.lower().strip()
        if priority:
            clauses.append("priority = :priority")
            params["priority"] = priority.lower().strip()
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += _TASK_ORDERING + " FETCH FIRST :lim ROWS ONLY"
        params["lim"] = max(1, int(limit))
        with self._lock:
            rows = self._query(query, params)
        return [TaskItem.from_mapping(row) for row in rows]

    def get_task(self, task_id: str) -> TaskItem | None:
        with self._lock:
            rows = self._query(
                f"SELECT {_TASK_COLUMNS} FROM user_tasks WHERE id = :id", {"id": task_id}
            )
        return TaskItem.from_mapping(rows[0]) if rows else None

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        due_at: float | None = None,
    ) -> TaskItem | None:
        item = self.get_task(task_id)
        if not item:
            return None

        if title is not None:
            item.title = title.strip()
        if description is not None:
            item.description = description.strip()
        if status is not None:
            item.status = status.lower().strip()
            if item.status == "completed" and not item.completed_at:
                item.completed_at = time.time()
        if priority is not None:
            item.priority = priority.lower().strip()
        if due_at is not None:
            item.due_at = due_at

        with self._lock:
            oracle.execute(
                "UPDATE user_tasks SET title = :title, description = :description, "
                "status = :status, priority = :priority, due_at = :due_at, "
                "completed_at = :completed_at WHERE id = :id",
                {
                    "title": item.title,
                    "description": oracle.nullif_empty(item.description),
                    "status": item.status,
                    "priority": item.priority,
                    "due_at": item.due_at,
                    "completed_at": item.completed_at,
                    "id": item.id,
                },
                engine=self.engine,
            )
        return item

    def complete_task(self, task_id_or_keyword: str) -> TaskItem | None:
        target = task_id_or_keyword.strip()
        item = self.get_task(target)
        if not item:
            with self._lock:
                rows = self._query(
                    "SELECT id FROM user_tasks WHERE status <> 'completed' "
                    "AND LOWER(title) LIKE :pat FETCH FIRST 1 ROWS ONLY",
                    {"pat": f"%{target.lower()}%"},
                )
            if rows:
                item = self.get_task(rows[0]["id"])

        if item:
            return self.update_task(item.id, status="completed")
        return None

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            return oracle.execute(
                "DELETE FROM user_tasks WHERE id = :id", {"id": task_id}, engine=self.engine
            ) > 0


def create_task_store(db_path: str | None = None, *, dsn: str | None = None) -> SQLiteTaskStore | OracleTaskStore:
    """Return the configured task store.

    ``db_path`` explicitly selects the test-only SQLite store and is rejected
    outside a pytest run. Without it the production Oracle store is used, and a
    missing Oracle DSN raises :class:`~friday.core.exceptions.PersistenceConfigError`
    rather than silently creating a SQLite file.
    """
    if db_path:
        return SQLiteTaskStore(db_path=db_path)
    return OracleTaskStore(dsn=dsn)

