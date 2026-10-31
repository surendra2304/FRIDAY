"""Tool for explicitly storing user facts, preferences, and memories in persistent storage.

Facts live in the ``FRIDAY`` Oracle schema (``user_memories``). Tests may pass an
explicit ``db_path`` to use a throwaway SQLite file; production never does.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from typing import Any

from friday.core import oracle
from friday.core.exceptions import PersistenceConfigError
from friday.core.logging import get_logger
from friday.core.oracle import ephemeral_backend_allowed
from friday.core.types import Message, Role, SafetyLevel, ToolResult
from friday.memory.base import BaseMemory
from friday.tools.base import BaseTool

logger = get_logger("tools.remember")


class RememberFactTool(BaseTool):
    """Explicitly store a user fact, preference, note, or reminder into persistent memory."""

    name = "remember_fact"
    description = (
        "Store an explicit fact, user preference, important date, or memory note into FRIDAY's persistent memory. "
        "Use this whenever the user says 'remember that...', 'keep in mind that...', or asks FRIDAY to remember something."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The exact fact, note, or statement the user wants remembered (e.g. 'My presentation is Friday at 3 PM').",
            },
            "category": {
                "type": "string",
                "description": "Optional category or tag: 'preference', 'schedule', 'personal', 'work', 'general'.",
            },
        },
        "required": ["fact"],
    }

    def __init__(self, memory: BaseMemory | None = None, db_path: str | None = None) -> None:
        super().__init__()
        self.memory = memory
        self.db_path = db_path
        self._lock = threading.RLock()
        if db_path is not None:
            if not ephemeral_backend_allowed():
                raise PersistenceConfigError(
                    "RememberFactTool(db_path=...) is test-only; omit db_path so "
                    "facts are written to Oracle Autonomous Database."
                )
            self._init_sqlite()
        else:
            # Schema bootstrap happens on first query/execute, never at import.
            pass

    def _init_sqlite(self) -> None:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_memories (
                    id TEXT PRIMARY KEY,
                    fact TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at REAL NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_cat ON user_memories(category);"
            )
            conn.commit()

    def _persist(self, mem_id: str, fact: str, category: str, created_at: float) -> None:
        if self.db_path is not None:
            with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
                conn.execute(
                    "INSERT INTO user_memories (id, fact, category, created_at) VALUES (?, ?, ?, ?);",
                    (mem_id, fact, category, created_at),
                )
                conn.commit()
            return
        oracle.execute(
            "INSERT INTO user_memories (id, fact, category, created_at) "
            "VALUES (:id, :fact, :category, :created_at)",
            {
                "id": mem_id,
                "fact": fact,
                "category": category,
                "created_at": created_at,
            },
        )

    def execute(self, fact: str, category: str = "general", **kwargs: Any) -> ToolResult:
        f = (fact or "").strip()
        if not f:
            return ToolResult(
                name=self.name,
                content="Error: 'fact' cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        cat = (category or "general").lower().strip()
        now = time.time()
        mem_id = f"mem_{uuid.uuid4().hex[:8]}"

        try:
            self._persist(mem_id, f, cat, now)
        except Exception as exc:
            logger.error("Failed to persist user memory: %s", exc)
            return ToolResult(
                name=self.name,
                content="Error: could not persist the fact; see server logs.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # Also append as a system/memory note in BaseMemory if attached
        if self.memory is not None:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"[USER MEMORY RECORDED]: {f} (Category: {cat})",
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"Could not append to conversation memory: {e}")

        # Synchronize fact to Memora Persistent Memory Fabric
        try:
            from friday.memory.memora_client import memora_client
            memora_client.record_fact("friday", fact_text=f, category=cat, importance=0.95)
        except Exception as e:
            logger.debug(f"Memora fact sync skipped: {e}")

        return ToolResult(
            name=self.name,
            content=f"I have remembered: '{f}' (Category: {cat}).",
            is_error=False,
            safety_level=self.safety_level,
        )
