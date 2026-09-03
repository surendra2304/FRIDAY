"""Tool for explicitly storing user facts, preferences, and memories in persistent storage."""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, ToolResult
from friday.memory.base import BaseMemory
from friday.tools.base import BaseTool

logger = get_logger("tools.remember")

DEFAULT_DB_PATH = "data/friday.db"


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

    def __init__(self, memory: BaseMemory | None = None, db_path: str = DEFAULT_DB_PATH) -> None:
        super().__init__()
        self.memory = memory
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_memories (
                        id TEXT PRIMARY KEY,
                        fact TEXT NOT NULL,
                        category TEXT DEFAULT 'general',
                        created_at REAL NOT NULL
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_cat ON user_memories(category);")
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not initialize user_memories table: {e}")

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

        # 1. Store in user_memories table
        try:
            with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
                conn.execute(
                    "INSERT INTO user_memories (id, fact, category, created_at) VALUES (?, ?, ?, ?);",
                    (mem_id, f, cat, now),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Failed to write to user_memories table: {e}")

        # 2. Also append as a system/memory note in BaseMemory if attached
        if self.memory is not None:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"[USER MEMORY RECORDED]: {f} (Category: {cat})",
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"Could not append to conversation memory: {e}")

        return ToolResult(
            name=self.name,
            content=f"I have remembered: '{f}' (Category: {cat}).",
            is_error=False,
            safety_level=self.safety_level,
        )
