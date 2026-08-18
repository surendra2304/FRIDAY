"""SQLite-backed conversation memory with ACID persistence and conversation isolation."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.memory.base import BaseMemory

logger = get_logger("memory.sqlite")


class SQLiteConversationMemory(BaseMemory):
    """Production-grade persistent conversation memory using SQLite."""

    def __init__(
        self,
        db_path: str = "data/friday.db",
        conversation_id: Optional[str] = None,
        max_messages: int = 50,
    ) -> None:
        self.db_path = db_path
        self.max_messages = max(2, max_messages)
        self._lock = threading.Lock()

        # Resolve path & ensure directory existence if not in-memory
        if self.db_path != ":memory:":
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self._active_conversation_id = conversation_id or self.create_conversation(title="Default Conversation")

    @property
    def active_conversation_id(self) -> str:
        """Return the currently active conversation ID."""
        return self._active_conversation_id

    def _get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection with foreign keys and WAL enabled."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=20.0,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        """Create schema tables and indexes if they do not exist."""
        with self._lock:
            with self._get_connection() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        title TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        name TEXT,
                        tool_calls TEXT,
                        tool_call_id TEXT,
                        created_at TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_conv_created 
                    ON messages(conversation_id, created_at);
                """)
                logger.debug(f"Initialized SQLite conversation database schema at '{self.db_path}'")

    def _get_or_create_default_conversation(self) -> str:
        """Find the latest active conversation or create a new default one."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row:
                    return str(row["id"])

        # Create default conversation
        return self.create_conversation(title="Default Conversation")

    def create_conversation(
        self,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new conversation session and return its ID."""
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {})

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO conversations (id, title, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (conv_id, title or "New Conversation", now, now, meta_str),
                )
                conn.commit()
                logger.info(f"Created conversation session '{conv_id}' [Title: '{title}']")

        self._active_conversation_id = conv_id
        return conv_id

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List stored conversations ordered by most recent update."""
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, title, created_at, updated_at, metadata,
                           (SELECT COUNT(*) FROM messages WHERE messages.conversation_id = conversations.id) AS message_count
                    FROM conversations
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

                result = []
                for r in rows:
                    meta = {}
                    if r["metadata"]:
                        try:
                            meta = json.loads(r["metadata"])
                        except Exception:
                            pass
                    result.append({
                        "id": r["id"],
                        "title": r["title"],
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "message_count": r["message_count"],
                        "metadata": meta,
                    })
                return result

    def load_conversation(self, conversation_id: str) -> None:
        """Set the active conversation ID after validating existence."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
                ).fetchone()
                if not row:
                    raise ValueError(f"Conversation '{conversation_id}' does not exist.")
        self._active_conversation_id = conversation_id
        logger.info(f"Loaded active conversation session: '{conversation_id}'")

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its cascade-referenced messages."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM conversations WHERE id = ?", (conversation_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0

        if deleted and self._active_conversation_id == conversation_id:
            # Switch to another conversation or create a new one
            self._active_conversation_id = self._get_or_create_default_conversation()
        return deleted

    def add_message(
        self,
        message: Message,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Persist a message into the conversation store."""
        conv_id = conversation_id or self._active_conversation_id
        msg_id = str(uuid.uuid4())
        created_at = message.timestamp.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        # Serialize tool calls explicitly
        tool_calls_str = None
        if message.tool_calls:
            tool_calls_str = json.dumps([
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in message.tool_calls
            ])

        with self._lock:
            with self._get_connection() as conn:
                # Ensure conversation exists
                conv = conn.execute(
                    "SELECT id FROM conversations WHERE id = ?", (conv_id,)
                ).fetchone()
                if not conv:
                    conn.execute(
                        """
                        INSERT INTO conversations (id, title, created_at, updated_at, metadata)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (conv_id, "Auto-created Conversation", created_at, now, "{}"),
                    )

                conn.execute(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg_id,
                        conv_id,
                        message.role.value,
                        message.content,
                        message.name,
                        tool_calls_str,
                        message.tool_call_id,
                        created_at,
                        "{}",
                    ),
                )

                # Update conversation last modified timestamp
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id)
                )
                conn.commit()
                logger.debug(f"Saved message '{msg_id}' [Role: {message.role.value}] to conversation '{conv_id}'")

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """Deserialize a SQLite row into a strongly-typed Message instance."""
        tool_calls = None
        if row["tool_calls"]:
            try:
                tc_data = json.loads(row["tool_calls"])
                if isinstance(tc_data, list):
                    tool_calls = [
                        ToolCall(
                            id=item.get("id", ""),
                            name=item.get("name", ""),
                            arguments=item.get("arguments", {}),
                        )
                        for item in tc_data
                    ]
            except Exception as e:
                logger.warning(f"Failed to deserialize tool_calls for message {row['id']}: {e}")

        # Parse timestamp safely
        try:
            ts = datetime.fromisoformat(row["created_at"])
        except Exception:
            ts = datetime.now(timezone.utc)

        return Message(
            role=Role(row["role"]),
            content=row["content"],
            name=row["name"],
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
            timestamp=ts,
        )

    def get_messages(self, conversation_id: Optional[str] = None) -> List[Message]:
        """Retrieve all stored messages for the conversation in chronological order."""
        conv_id = conversation_id or self._active_conversation_id
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (conv_id,),
                ).fetchall()
                return [self._row_to_message(r) for r in rows]

    def get_context_window(
        self,
        max_messages: int,
        conversation_id: Optional[str] = None,
    ) -> List[Message]:
        """Retrieve recent slice of messages up to max_messages for active context window."""
        if max_messages <= 0:
            return []

        conv_id = conversation_id or self._active_conversation_id
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata
                    FROM (
                        SELECT id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata, rowid
                        FROM messages
                        WHERE conversation_id = ?
                        ORDER BY created_at DESC, rowid DESC
                        LIMIT ?
                    ) sub
                    ORDER BY created_at ASC, rowid ASC
                    """,
                    (conv_id, max_messages),
                ).fetchall()
                return [self._row_to_message(r) for r in rows]

    def clear(self, conversation_id: Optional[str] = None) -> None:
        """Clear all messages from the conversation."""
        conv_id = conversation_id or self._active_conversation_id
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM messages WHERE conversation_id = ?", (conv_id,)
                )
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id)
                )
                conn.commit()
                logger.debug(f"Cleared messages in conversation '{conv_id}'")

    def __len__(self) -> int:
        """Return total message count in active conversation."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?",
                    (self._active_conversation_id,),
                ).fetchone()
                return int(row["count"]) if row else 0
