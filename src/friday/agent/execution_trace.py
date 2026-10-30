"""Execution Trace Checkpoint Persistence for FRIDAY Core.

Persists distributed inter-agent execution traces, task receipts, retry telemetry
and multi-agent consensus checkpoints into Oracle Autonomous Database
(``FRIDAY.execution_traces``) through the shared engine in
:mod:`friday.core.oracle`.

Backends:

* Oracle is the default when no ``db_path`` is supplied. The engine is resolved
  lazily so importing this module -- and the module-level ``trace_store``
  singleton -- never opens a socket.
* SQLite is still available by passing ``db_path`` explicitly (local development
  and the existing unit tests).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
)

from friday.core import oracle
from friday.core.database import get_db_connection
from friday.core.exceptions import PersistenceConfigError
from friday.core.logging import get_logger

logger = get_logger("agent.execution_trace")

#: Legacy PostgreSQL/SQLite table description, kept for callers that import it.
metadata = MetaData()
execution_traces_table = Table(
    "execution_traces",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trace_id", String(64), nullable=False, index=True),
    Column("task_id", String(64), nullable=False, index=True),
    Column("target_agent", String(64), nullable=False, index=True),
    Column("action", String(256), nullable=False),
    Column("status", String(32), nullable=False, index=True),
    Column("consensus_status", String(32), default="NONE"),
    Column("participating_agents", Text, default="[]"),
    Column("agreement_ratio", Float, default=1.0),
    Column("latency_ms", Integer, default=0),
    Column("retry_count", Integer, default=0),
    Column("payload_summary", Text, default=""),
    Column("result_summary", Text, default=""),
    Column("error", Text, default=""),
    Column("receipt_json", Text, default="{}"),
    Column("created_at", String(64), nullable=False, index=True),
)

#: Columns read from Oracle -- CLOB columns are suffixed to avoid reserved words.
_ORACLE_SELECT = (
    "SELECT id, trace_id, task_id, target_agent, action, status, consensus_status, "
    "participating_agents_json, agreement_ratio, latency_ms, retry_count, "
    "payload_summary, result_summary, error, receipt_json, created_at "
    "FROM execution_traces"
)


def get_postgres_dsn() -> str | None:
    """Resolve the Oracle Autonomous Database DSN.

    Kept under its historical name because tests and callers import it. Oracle
    URLs are normalised to ``oracle+oracledb://``: SQLAlchemy 2.x serves sync and
    async Oracle engines from that single dialect. PostgreSQL and SQLite are not
    supported backends.
    """
    raw_url = (
        os.getenv("ORACLE_CORE_ASYNC_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("FRIDAY_DATABASE_URL")
    )
    if raw_url:
        if raw_url.startswith("oracle://"):
            return raw_url.replace("oracle://", "oracle+oracledb://", 1)
        return raw_url
    return None


@dataclass(frozen=True)
class ExecutionTraceCheckpoint:
    trace_id: str
    task_id: str
    target_agent: str
    action: str
    status: str
    consensus_status: str = "NONE"
    participating_agents: list[str] = field(default_factory=list)
    agreement_ratio: float = 1.0
    latency_ms: int = 0
    retry_count: int = 0
    payload_summary: str = ""
    result_summary: str = ""
    error: str = ""
    receipt_json: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionTraceStore:
    """Manages persistent execution trace checkpoints in Oracle (or SQLite)."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        postgres_dsn: Optional[str] = None,
        enable_postgres: bool = True,
        *,
        dsn: Optional[str] = None,
    ) -> None:
        self.db_path = db_path
        self.enable_postgres = enable_postgres
        self._postgres_dsn = postgres_dsn or get_postgres_dsn()
        self._backend = "sqlite" if db_path else "oracle"
        self._oracle_engine: Any | None = None
        self._oracle_dsn = dsn
        self._oracle_disabled = False
        self._last_postgres_failure: float = 0.0

        if db_path:
            self._init_sqlite()

    # ------------------------------------------------------------------
    # Backend plumbing
    # ------------------------------------------------------------------
    @property
    def backend(self) -> str:
        """Active storage backend: ``oracle`` or ``sqlite``."""
        return self._backend

    def _ensure_oracle(self) -> Any | None:
        """Resolve the shared Oracle engine lazily (never at import time)."""
        if self._oracle_disabled:
            return None
        if self._oracle_engine is None:
            try:
                self._oracle_engine = oracle.get_engine(self._oracle_dsn)
            except PersistenceConfigError:
                if not oracle.ephemeral_backend_allowed():
                    raise
                logger.warning(
                    "No Oracle DSN configured; execution traces are not persisted "
                    "because this process is a test run."
                )
                self._oracle_disabled = True
                return None
        return self._oracle_engine

    def _init_sqlite(self) -> None:
        """Create execution_traces table in SQLite if it doesn't exist."""
        try:
            with get_db_connection(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_traces (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trace_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,
                        target_agent TEXT NOT NULL,
                        action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        consensus_status TEXT DEFAULT 'NONE',
                        participating_agents TEXT DEFAULT '[]',
                        agreement_ratio REAL DEFAULT 1.0,
                        latency_ms INTEGER DEFAULT 0,
                        retry_count INTEGER DEFAULT 0,
                        payload_summary TEXT DEFAULT '',
                        result_summary TEXT DEFAULT '',
                        error TEXT DEFAULT '',
                        receipt_json TEXT DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON execution_traces(trace_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_task_id ON execution_traces(task_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_target_agent ON execution_traces(target_agent)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_status ON execution_traces(status)")
        except Exception as exc:
            logger.warning("Failed to initialize SQLite execution_traces: %s", exc)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def _sync_sqlite_insert(self, cp: ExecutionTraceCheckpoint) -> int:
        """Insert trace checkpoint into SQLite synchronously."""
        try:
            with get_db_connection(self.db_path) as conn:
                agents_json = json.dumps(cp.participating_agents)
                cur = conn.execute(
                    """
                    INSERT INTO execution_traces (
                        trace_id, task_id, target_agent, action, status,
                        consensus_status, participating_agents, agreement_ratio,
                        latency_ms, retry_count, payload_summary, result_summary,
                        error, receipt_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cp.trace_id,
                        cp.task_id,
                        cp.target_agent,
                        cp.action,
                        cp.status,
                        cp.consensus_status,
                        agents_json,
                        float(cp.agreement_ratio),
                        int(cp.latency_ms),
                        int(cp.retry_count),
                        cp.payload_summary,
                        cp.result_summary,
                        cp.error,
                        cp.receipt_json,
                        cp.created_at,
                    ),
                )
                conn.commit()
                return cur.lastrowid or 0
        except Exception as exc:
            logger.warning("Failed to insert execution trace to SQLite: %s", exc)
            return 0

    def _sync_oracle_insert(self, cp: ExecutionTraceCheckpoint) -> int:
        """Insert a trace row into Oracle and return its identity value."""
        engine = self._ensure_oracle()
        if engine is None:
            return 0
        table = oracle.execution_traces_table
        try:
            with engine.begin() as conn:
                result = conn.execute(
                    insert(table)
                    .values(
                        trace_id=cp.trace_id,
                        task_id=cp.task_id,
                        target_agent=cp.target_agent,
                        action=cp.action,
                        status=cp.status,
                        consensus_status=cp.consensus_status,
                        participating_agents_json=json.dumps(cp.participating_agents),
                        agreement_ratio=float(cp.agreement_ratio),
                        latency_ms=int(cp.latency_ms),
                        retry_count=int(cp.retry_count),
                        payload_summary=oracle.nullif_empty(cp.payload_summary),
                        result_summary=oracle.nullif_empty(cp.result_summary),
                        error=oracle.nullif_empty(cp.error),
                        receipt_json=cp.receipt_json,
                        created_at=cp.created_at,
                    )
                    .returning(table.c.id)
                )
                return int(result.scalar_one())
        except Exception as exc:
            logger.warning("Failed to insert execution trace to Oracle: %s", exc)
            return 0

    def _sync_insert(self, cp: ExecutionTraceCheckpoint) -> int:
        if self._backend == "sqlite":
            return self._sync_sqlite_insert(cp)
        return self._sync_oracle_insert(cp)

    async def record_checkpoint_async(self, cp: ExecutionTraceCheckpoint) -> ExecutionTraceCheckpoint:
        """Persist a trace checkpoint without blocking the event loop."""
        inserted_id = await asyncio.to_thread(self._sync_insert, cp)
        return self._with_id(cp, inserted_id)

    def record_checkpoint(self, cp: ExecutionTraceCheckpoint) -> ExecutionTraceCheckpoint:
        """Persist a trace checkpoint synchronously."""
        return self._with_id(cp, self._sync_insert(cp))

    @staticmethod
    def _with_id(cp: ExecutionTraceCheckpoint, assigned_id: int) -> ExecutionTraceCheckpoint:
        return ExecutionTraceCheckpoint(
            id=assigned_id or None,
            trace_id=cp.trace_id,
            task_id=cp.task_id,
            target_agent=cp.target_agent,
            action=cp.action,
            status=cp.status,
            consensus_status=cp.consensus_status,
            participating_agents=cp.participating_agents,
            agreement_ratio=cp.agreement_ratio,
            latency_ms=cp.latency_ms,
            retry_count=cp.retry_count,
            payload_summary=cp.payload_summary,
            result_summary=cp.result_summary,
            error=cp.error,
            receipt_json=cp.receipt_json,
            created_at=cp.created_at,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _agents(raw: Any) -> list[str]:
        try:
            parsed = json.loads(raw or "[]")
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []

    @classmethod
    def _from_oracle_row(cls, row: dict[str, Any]) -> ExecutionTraceCheckpoint:
        return cls._from_mapping(row, "participating_agents_json")

    @classmethod
    def _from_sqlite_row(cls, row: Any) -> ExecutionTraceCheckpoint:
        return cls._from_mapping(row, "participating_agents")

    @classmethod
    def _from_mapping(cls, row: Any, agents_key: str) -> ExecutionTraceCheckpoint:
        return ExecutionTraceCheckpoint(
            id=row["id"],
            trace_id=row["trace_id"],
            task_id=row["task_id"],
            target_agent=row["target_agent"],
            action=row["action"],
            status=row["status"],
            consensus_status=row["consensus_status"],
            participating_agents=cls._agents(row[agents_key]),
            agreement_ratio=row["agreement_ratio"],
            latency_ms=row["latency_ms"],
            retry_count=row["retry_count"],
            payload_summary=row["payload_summary"],
            result_summary=row["result_summary"],
            error=row["error"],
            receipt_json=row["receipt_json"],
            created_at=row["created_at"],
        )

    def _oracle_traces(self, where: str = "", params: dict[str, Any] | None = None, limit: int = 50) -> list[ExecutionTraceCheckpoint]:
        engine = self._ensure_oracle()
        if engine is None:
            return []
        sql = _ORACLE_SELECT + (f" WHERE {where}" if where else "")
        sql += " ORDER BY id DESC FETCH FIRST :lim ROWS ONLY"
        rows = oracle.query_all(sql, {**(params or {}), "lim": max(1, int(limit))}, engine=engine)
        return [self._from_oracle_row(row) for row in rows]

    def get_recent_traces(
        self,
        limit: int = 50,
        target_agent: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[ExecutionTraceCheckpoint]:
        """Fetch recent execution traces."""
        if self._backend == "oracle":
            try:
                conditions: list[str] = []
                params: dict[str, Any] = {}
                if target_agent:
                    conditions.append("target_agent = :agent")
                    params["agent"] = target_agent
                if status:
                    conditions.append("status = :status")
                    params["status"] = status
                return self._oracle_traces(" AND ".join(conditions), params, limit)
            except Exception as exc:
                logger.warning("Failed to query execution_traces from Oracle: %s", exc)
                return []

        traces: list[ExecutionTraceCheckpoint] = []
        try:
            with get_db_connection(self.db_path) as conn:
                query = "SELECT * FROM execution_traces"
                conditions: list[str] = []
                params: list[Any] = []
                if target_agent:
                    conditions.append("target_agent = ?")
                    params.append(target_agent)
                if status:
                    conditions.append("status = ?")
                    params.append(status)
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY id DESC LIMIT ?"
                params.append(limit)

                cur = conn.execute(query, params)
                for row in cur.fetchall():
                    traces.append(self._from_sqlite_row(row))
        except Exception as exc:
            logger.warning("Failed to query execution_traces from SQLite: %s", exc)
        return traces

    def get_trace_by_id(self, trace_id: str) -> Optional[ExecutionTraceCheckpoint]:
        """Fetch single trace checkpoint by trace_id."""
        if self._backend == "oracle":
            try:
                rows = self._oracle_traces("trace_id = :tid", {"tid": trace_id}, limit=1)
                return rows[0] if rows else None
            except Exception as exc:
                logger.warning("Failed to query trace_id %s from Oracle: %s", trace_id, exc)
                return None

        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute(
                    "SELECT * FROM execution_traces WHERE trace_id = ? ORDER BY id DESC LIMIT 1",
                    (trace_id,),
                )
                row = cur.fetchone()
                return self._from_sqlite_row(row) if row else None
        except Exception as exc:
            logger.warning("Failed to query trace_id %s: %s", trace_id, exc)
            return None

    def get_consensus_traces(self, limit: int = 50) -> list[ExecutionTraceCheckpoint]:
        """Fetch traces that were executed under multi-agent consensus routing."""
        if self._backend == "oracle":
            try:
                return self._oracle_traces("consensus_status <> 'NONE'", None, limit)
            except Exception as exc:
                logger.warning("Failed to query consensus traces from Oracle: %s", exc)
                return []

        traces: list[ExecutionTraceCheckpoint] = []
        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute(
                    """
                    SELECT * FROM execution_traces
                    WHERE consensus_status != 'NONE'
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                )
                for row in cur.fetchall():
                    traces.append(self._from_sqlite_row(row))
        except Exception as exc:
            logger.warning("Failed to query consensus traces: %s", exc)
        return traces


# Global singleton instance. Construction is side-effect free: the Oracle engine
# (and therefore the schema bootstrap) is resolved on first use.
trace_store = ExecutionTraceStore()
