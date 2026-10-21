"""Execution Trace Checkpoint Persistence for FRIDAY Core.

Persists distributed inter-agent execution traces, task receipts, retry telemetry,
and multi-agent consensus checkpoints directly into `friday_db.execution_traces` in
PostgreSQL via SQLAlchemy / asyncpg, with seamless local SQLite fallback for
zero-downtime offline and desktop execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    desc,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from friday.core.database import get_db_connection
from friday.core.logging import get_logger

logger = get_logger("agent.execution_trace")

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


def get_postgres_dsn() -> str | None:
    """Resolve PostgreSQL asyncpg DSN with fallback to friday_db defaults."""
    raw_url = os.getenv("DATABASE_URL") or os.getenv("FRIDAY_DATABASE_URL")
    if raw_url:
        if raw_url.startswith("postgresql://"):
            return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif raw_url.startswith("postgres://"):
            return raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
        return raw_url

    host = os.getenv("POSTGRES_HOST") or os.getenv("FRIDAY_POSTGRES_HOST")
    if not host:
        return None

    port = os.getenv("POSTGRES_PORT") or os.getenv("FRIDAY_POSTGRES_PORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("FRIDAY_POSTGRES_DB") or "friday_db"
    user = os.getenv("POSTGRES_USER") or os.getenv("FRIDAY_POSTGRES_USER") or "friday_user"
    pw = os.getenv("POSTGRES_PASSWORD") or os.getenv("FRIDAY_POSTGRES_PASSWORD") or ""

    return f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{db}"


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
    """Manages persistent execution trace checkpoints in PostgreSQL & SQLite."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        postgres_dsn: Optional[str] = None,
        enable_postgres: bool = True,
    ) -> None:
        if not db_path:
            base_dir = Path.home() / ".friday"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "traces.db")
        self.db_path = db_path
        self.enable_postgres = enable_postgres
        self._postgres_dsn = postgres_dsn or get_postgres_dsn()
        self._engine: Optional[AsyncEngine] = None
        self._postgres_available: Optional[bool] = None
        self._last_postgres_failure: float = 0.0

        self._init_sqlite()

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

    async def _get_engine(self) -> Optional[AsyncEngine]:
        """Lazy-initialize asyncpg engine for PostgreSQL."""
        if not self.enable_postgres or not self._postgres_dsn:
            return None

        # Backoff for 60 seconds if PostgreSQL failed recently
        if self._postgres_available is False:
            if time.monotonic() - self._last_postgres_failure < 60.0:
                return None

        if self._engine is None:
            try:
                self._engine = create_async_engine(
                    self._postgres_dsn,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                    connect_args={"timeout": 5.0},
                )
                # Verify connection and ensure schema
                async with self._engine.begin() as conn:
                    await conn.run_sync(metadata.create_all)
                self._postgres_available = True
            except Exception as exc:
                logger.warning("PostgreSQL connection to friday_db.execution_traces failed: %s", exc)
                self._postgres_available = False
                self._last_postgres_failure = time.monotonic()
                return None

        return self._engine

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

    async def record_checkpoint_async(self, cp: ExecutionTraceCheckpoint) -> ExecutionTraceCheckpoint:
        """Persist trace checkpoint to PostgreSQL if online, mirroring to SQLite."""
        engine = await self._get_engine()
        agents_json = json.dumps(cp.participating_agents)
        pg_inserted_id = None

        if engine is not None and self._postgres_available is not False:
            try:
                async with engine.begin() as conn:
                    stmt = (
                        execution_traces_table.insert()
                        .values(
                            trace_id=cp.trace_id,
                            task_id=cp.task_id,
                            target_agent=cp.target_agent,
                            action=cp.action,
                            status=cp.status,
                            consensus_status=cp.consensus_status,
                            participating_agents=agents_json,
                            agreement_ratio=float(cp.agreement_ratio),
                            latency_ms=int(cp.latency_ms),
                            retry_count=int(cp.retry_count),
                            payload_summary=cp.payload_summary,
                            result_summary=cp.result_summary,
                            error=cp.error,
                            receipt_json=cp.receipt_json,
                            created_at=cp.created_at,
                        )
                        .returning(execution_traces_table.c.id)
                    )
                    res = await conn.execute(stmt)
                    pg_inserted_id = res.scalar_one_or_none()
                    self._postgres_available = True
            except Exception as exc:
                logger.warning("PostgreSQL record_checkpoint_async failed, falling back to SQLite: %s", exc)
                self._postgres_available = False
                self._last_postgres_failure = time.monotonic()

        sqlite_id = self._sync_sqlite_insert(cp)
        assigned_id = pg_inserted_id if pg_inserted_id is not None else sqlite_id
        return ExecutionTraceCheckpoint(
            id=assigned_id,
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

    def record_checkpoint(self, cp: ExecutionTraceCheckpoint) -> ExecutionTraceCheckpoint:
        """Synchronously persist to SQLite and queue non-blocking async PostgreSQL write."""
        sqlite_id = self._sync_sqlite_insert(cp)
        res_cp = ExecutionTraceCheckpoint(
            id=sqlite_id,
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

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.record_checkpoint_async(cp))
        except RuntimeError:
            pass

        return res_cp

    def get_recent_traces(
        self,
        limit: int = 50,
        target_agent: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[ExecutionTraceCheckpoint]:
        """Fetch recent execution traces from local store."""
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
                    agents = []
                    try:
                        agents = json.loads(row["participating_agents"] or "[]")
                    except Exception:
                        pass
                    traces.append(
                        ExecutionTraceCheckpoint(
                            id=row["id"],
                            trace_id=row["trace_id"],
                            task_id=row["task_id"],
                            target_agent=row["target_agent"],
                            action=row["action"],
                            status=row["status"],
                            consensus_status=row["consensus_status"],
                            participating_agents=agents,
                            agreement_ratio=row["agreement_ratio"],
                            latency_ms=row["latency_ms"],
                            retry_count=row["retry_count"],
                            payload_summary=row["payload_summary"],
                            result_summary=row["result_summary"],
                            error=row["error"],
                            receipt_json=row["receipt_json"],
                            created_at=row["created_at"],
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to query execution_traces from SQLite: %s", exc)
        return traces

    def get_trace_by_id(self, trace_id: str) -> Optional[ExecutionTraceCheckpoint]:
        """Fetch single trace checkpoint by trace_id."""
        try:
            with get_db_connection(self.db_path) as conn:
                cur = conn.execute(
                    "SELECT * FROM execution_traces WHERE trace_id = ? ORDER BY id DESC LIMIT 1",
                    (trace_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                agents = []
                try:
                    agents = json.loads(row["participating_agents"] or "[]")
                except Exception:
                    pass
                return ExecutionTraceCheckpoint(
                    id=row["id"],
                    trace_id=row["trace_id"],
                    task_id=row["task_id"],
                    target_agent=row["target_agent"],
                    action=row["action"],
                    status=row["status"],
                    consensus_status=row["consensus_status"],
                    participating_agents=agents,
                    agreement_ratio=row["agreement_ratio"],
                    latency_ms=row["latency_ms"],
                    retry_count=row["retry_count"],
                    payload_summary=row["payload_summary"],
                    result_summary=row["result_summary"],
                    error=row["error"],
                    receipt_json=row["receipt_json"],
                    created_at=row["created_at"],
                )
        except Exception as exc:
            logger.warning("Failed to query trace_id %s: %s", trace_id, exc)
            return None

    def get_consensus_traces(self, limit: int = 50) -> list[ExecutionTraceCheckpoint]:
        """Fetch traces that were executed under multi-agent consensus routing."""
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
                    agents = []
                    try:
                        agents = json.loads(row["participating_agents"] or "[]")
                    except Exception:
                        pass
                    traces.append(
                        ExecutionTraceCheckpoint(
                            id=row["id"],
                            trace_id=row["trace_id"],
                            task_id=row["task_id"],
                            target_agent=row["target_agent"],
                            action=row["action"],
                            status=row["status"],
                            consensus_status=row["consensus_status"],
                            participating_agents=agents,
                            agreement_ratio=row["agreement_ratio"],
                            latency_ms=row["latency_ms"],
                            retry_count=row["retry_count"],
                            payload_summary=row["payload_summary"],
                            result_summary=row["result_summary"],
                            error=row["error"],
                            receipt_json=row["receipt_json"],
                            created_at=row["created_at"],
                        )
                    )
        except Exception as exc:
            logger.warning("Failed to query consensus traces: %s", exc)
        return traces


# Global singleton instance
trace_store = ExecutionTraceStore()
