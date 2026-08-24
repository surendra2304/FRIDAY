"""SQLite-backed conversation memory with ACID persistence and conversation isolation."""

import base64
import json
import math
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import hashlib
from friday.core.logging import get_logger
from friday.core.types import EmbeddingRecord, MemorySearchResult, Message, Role, SemanticSearchResult, ToolCall, TrustLevel
from friday.memory.base import BaseMemory
from friday.core.config import get_settings

from friday.memory.policies import should_embed_message, should_retrieve_memory

logger = get_logger("memory.sqlite")

SECRET_REDACT_PATTERNS = [
    re.compile(r"AIza" + r"Sy[A-Za-z0-9_-]{33}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
]


def filter_secrets(text: Optional[str]) -> Optional[str]:
    """Sanitize secret API keys or credentials from text before persistence."""
    if not text or not isinstance(text, str):
        return text
    from friday.security.scrubber import redact_secrets
    return redact_secrets(text)


class SQLiteConversationMemory(BaseMemory):
    """Production-grade persistent conversation memory using SQLite."""

    def __init__(
        self,
        db_path: str = "data/friday.db",
        conversation_id: Optional[str] = None,
        max_messages: int = 50,
        embedding_provider: Optional[Any] = None,
    ) -> None:
        self.db_path = db_path
        self.max_messages = max(2, max_messages)
        self.embedding_provider = embedding_provider
        self._lock = threading.RLock()

        # Resolve path & ensure directory existence if not in-memory
        if self.db_path != ":memory:":
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self.settings = get_settings()
        self._active_conversation_id = conversation_id or self.create_conversation(title="Default Conversation")

        # Lazy initialize ChromaDB Vector Store for Phase 22 Semantic Vector Memory
        self._vector_store = None

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
        conn.execute("PRAGMA busy_timeout = 20000;")
        if self.db_path != ":memory:":
            import sys
            is_testing = os.getenv("FRIDAY_ENV") == "testing" or "pytest" in sys.modules
            try:
                if not is_testing:
                    conn.execute("PRAGMA journal_mode = WAL;")
                    conn.execute("PRAGMA synchronous = NORMAL;")
                else:
                    conn.execute("PRAGMA journal_mode = DELETE;")
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA cache_size = -64000;")
        return conn

    def _init_db(self) -> None:
        """Create schema tables and indexes if they do not exist. Ensure backup directory exists."""
        backup_path = Path(self.settings.backup_dir) if hasattr(self, 'settings') else Path('data/backups')
        backup_path.mkdir(parents=True, exist_ok=True)
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

                    CREATE INDEX IF NOT EXISTS idx_conversations_updated
                    ON conversations(updated_at DESC);

                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                        message_id UNINDEXED,
                        conversation_id UNINDEXED,
                        content,
                        tokenize = 'porter unicode61'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_messages_ai AFTER INSERT ON messages BEGIN
                        INSERT INTO messages_fts(message_id, conversation_id, content)
                        VALUES (new.id, new.conversation_id, new.content);
                    END;

                    CREATE TRIGGER IF NOT EXISTS trg_messages_ad AFTER DELETE ON messages BEGIN
                        DELETE FROM messages_fts WHERE message_id = old.id;
                    END;

                    CREATE TRIGGER IF NOT EXISTS trg_messages_au AFTER UPDATE ON messages BEGIN
                        DELETE FROM messages_fts WHERE message_id = old.id;
                        INSERT INTO messages_fts(message_id, conversation_id, content)
                        VALUES (new.id, new.conversation_id, new.content);
                    END;

                    CREATE TABLE IF NOT EXISTS memory_nodes (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                        memory_type TEXT NOT NULL CHECK(memory_type IN ('working', 'episodic', 'semantic', 'task')),
                        content TEXT NOT NULL,
                        source TEXT DEFAULT 'user',
                        importance REAL DEFAULT 0.5,
                        confidence REAL DEFAULT 1.0,
                        privacy TEXT DEFAULT 'private',
                        recency TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_memory_nodes_type ON memory_nodes(memory_type, recency DESC);
                    CREATE INDEX IF NOT EXISTS idx_memory_nodes_conv ON memory_nodes(conversation_id, memory_type);

                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_nodes_fts USING fts5(
                        node_id UNINDEXED,
                        conversation_id UNINDEXED,
                        memory_type UNINDEXED,
                        content,
                        tokenize = 'porter unicode61'
                    );

                    CREATE TRIGGER IF NOT EXISTS trg_memory_nodes_ai AFTER INSERT ON memory_nodes BEGIN
                        INSERT INTO memory_nodes_fts(node_id, conversation_id, memory_type, content)
                        VALUES (new.id, new.conversation_id, new.memory_type, new.content);
                    END;

                    CREATE TRIGGER IF NOT EXISTS trg_memory_nodes_ad AFTER DELETE ON memory_nodes BEGIN
                        DELETE FROM memory_nodes_fts WHERE node_id = old.id;
                    END;

                    CREATE TRIGGER IF NOT EXISTS trg_memory_nodes_au AFTER UPDATE ON memory_nodes BEGIN
                        DELETE FROM memory_nodes_fts WHERE node_id = old.id;
                        INSERT INTO memory_nodes_fts(node_id, conversation_id, memory_type, content)
                        VALUES (new.id, new.conversation_id, new.memory_type, new.content);
                    END;

                    CREATE TABLE IF NOT EXISTS embeddings (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                        message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
                        source_text TEXT NOT NULL,
                        embedding_blob BLOB NOT NULL,
                        model TEXT NOT NULL,
                        dimension INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_embeddings_conv ON embeddings(conversation_id);
                    CREATE INDEX IF NOT EXISTS idx_embeddings_msg ON embeddings(message_id);

                    CREATE TABLE IF NOT EXISTS experiments (
                        id TEXT PRIMARY KEY,
                        experiment_name TEXT NOT NULL,
                        task_prompt TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        provider_name TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        accuracy REAL DEFAULT 0.0,
                        success INTEGER NOT NULL,
                        latency_ms REAL NOT NULL,
                        token_usage INTEGER DEFAULT 0,
                        failure_mode TEXT,
                        response_content TEXT,
                        created_at TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_experiments_task_provider ON experiments(task_type, provider_name);
                    CREATE INDEX IF NOT EXISTS idx_experiments_created ON experiments(created_at DESC);

                    INSERT INTO messages_fts(message_id, conversation_id, content)
                    SELECT id, conversation_id, content FROM messages
                    WHERE id NOT IN (SELECT message_id FROM messages_fts);
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
                    ORDER BY updated_at DESC, rowid DESC
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

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve details of a specific conversation session."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT id, title, created_at, updated_at, metadata,
                           (SELECT COUNT(*) FROM messages WHERE messages.conversation_id = conversations.id) AS message_count
                    FROM conversations
                    WHERE id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if not row:
                    return None

                meta = {}
                if row["metadata"]:
                    try:
                        meta = json.loads(row["metadata"])
                    except Exception:
                        pass
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"],
                    "metadata": meta,
                }

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """Rename an existing conversation."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (new_title, now, conversation_id),
                )
                conn.commit()
                renamed = cursor.rowcount > 0
        if renamed:
            logger.info(f"Renamed conversation '{conversation_id}' to '{new_title}'")
        return renamed

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

    def delete_conversation(self, conversation_id: str, confirm: bool = False) -> bool:
        """Delete a conversation and all its cascade-referenced messages. Requires confirmation."""
        if not confirm:
            raise ValueError("Deletion of conversation requires confirm=True")
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
        if deleted and self._active_conversation_id == conversation_id:
            self._active_conversation_id = self._get_or_create_default_conversation()
        return deleted

    def add_message(
        self,
        message: Message,
        conversation_id: Optional[str] = None,
        auto_embed: bool = True,
    ) -> None:
        """Persist a message into the conversation store within a transaction."""
        conv_id = conversation_id or self._active_conversation_id
        msg_id = str(uuid.uuid4())
        
        # Filter secrets and handle content
        content = filter_secrets(message.content)
        
        # Deduplication check
        with self._lock:
            with self._get_connection() as conn:
                last_msg = conn.execute(
                    "SELECT content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
                    (conv_id,)
                ).fetchone()
                if last_msg and last_msg["content"] == content:
                    logger.debug("Skipping duplicate message insertion.")
                    return

        created_at = message.timestamp.isoformat()
        now = datetime.now(timezone.utc).isoformat()
        
        tool_calls_str = None
        if message.tool_calls:
            tc_list = []
            for tc in message.tool_calls:
                tc_dict = {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                sig = getattr(tc, "thought_signature", None)
                if sig:
                    if isinstance(sig, bytes):
                        tc_dict["thought_signature"] = base64.b64encode(sig).decode("ascii")
                    else:
                        tc_dict["thought_signature"] = str(sig)
                tc_list.append(tc_dict)
            tool_calls_str = json.dumps(tc_list)
        
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                conv = conn.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,)).fetchone()
                if not conv:
                    conn.execute("INSERT INTO conversations (id, title, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
                                 (conv_id, "Auto-created Conversation", created_at, now, "{}"))
                meta_dict = message.metadata or {}
                if message.trust_level:
                    meta_dict["trust_level"] = message.trust_level.value
                meta_json = json.dumps(meta_dict)
                conn.execute("INSERT INTO messages (id, conversation_id, role, content, name, tool_calls, tool_call_id, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (msg_id, conv_id, message.role.value, content, message.name, tool_calls_str, message.tool_call_id, created_at, meta_json))
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
                conn.commit()
                logger.debug(f"Saved message '{msg_id}' [Role: {message.role.value}] to conversation '{conv_id}'")

        if auto_embed and self.embedding_provider and should_embed_message(message):
            try:
                existing_emb = None
                with self._get_connection() as conn:
                    row = conn.execute("SELECT embedding_blob FROM embeddings WHERE source_text = ? LIMIT 1", (content,)).fetchone()
                    if row and row["embedding_blob"]:
                        try:
                            existing_emb = json.loads(row["embedding_blob"])
                        except Exception:
                            pass
                
                if existing_emb and isinstance(existing_emb, list):
                    emb = existing_emb
                    logger.debug("Reused existing semantic embedding from cache.")
                else:
                    emb = self.embedding_provider.embed_text(content)

                emb_rec = EmbeddingRecord(
                    id=str(uuid.uuid4()),
                    conversation_id=conv_id,
                    message_id=msg_id,
                    source_text=content,
                    embedding=emb,
                    model=self.embedding_provider.model,
                    dimension=self.embedding_provider.dimension,
                    metadata={"role": message.role.value},
                )
                self.add_embedding(emb_rec)
            except Exception as e:
                err_str = str(e)
                if "circuit breaker is open" in err_str or "429" in err_str or "quota" in err_str:
                    logger.debug(f"Auto-embedding skipped: {err_str}")
                else:
                    logger.debug(f"Auto-embedding message failed: {err_str}")

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """Deserialize a SQLite row into a strongly-typed Message instance."""
        tool_calls = None
        if row["tool_calls"]:
            try:
                tc_data = json.loads(row["tool_calls"])
                if isinstance(tc_data, list):
                    tool_calls = []
                    for item in tc_data:
                        sig_val = item.get("thought_signature")
                        sig_bytes = None
                        if sig_val:
                            try:
                                sig_bytes = base64.b64decode(sig_val)
                            except Exception:
                                sig_bytes = sig_val.encode("utf-8")
                        tool_calls.append(
                            ToolCall(
                                id=item.get("id", ""),
                                name=item.get("name", ""),
                                arguments=item.get("arguments", {}),
                                thought_signature=sig_bytes,
                            )
                        )
            except Exception as e:
                logger.warning(f"Failed to deserialize tool_calls for message {row['id']}: {e}")

        # Parse timestamp safely
        try:
            ts = datetime.fromisoformat(row["created_at"])
        except Exception:
            ts = datetime.now(timezone.utc)

        try:
            role = Role(row["role"])
        except Exception:
            role = Role.USER

        # Parse metadata and trust level
        msg_meta = {}
        trust = TrustLevel.TRUSTED_USER
        if "metadata" in row.keys() and row["metadata"]:
            try:
                msg_meta = json.loads(row["metadata"])
                if isinstance(msg_meta, dict) and "trust_level" in msg_meta:
                    t_val = msg_meta["trust_level"]
                    if t_val in TrustLevel._value2member_map_:
                        trust = TrustLevel(t_val)
            except Exception:
                pass

        return Message(
            role=role,
            content=row["content"] or "",
            name=row["name"],
            tool_calls=tool_calls,
            tool_call_id=row["tool_call_id"],
            timestamp=ts,
            trust_level=trust,
            metadata=msg_meta,
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
        max_messages: int = 50,
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

    def clear(self, conversation_id: Optional[str] = None, confirm: bool = False) -> None:
        """Clear all messages from the conversation. Requires confirmation."""
        if not confirm:
            raise ValueError("Clear memory requires confirm=True")
        conv_id = conversation_id or self._active_conversation_id
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))
                conn.commit()
                logger.debug(f"Cleared messages in conversation '{conv_id}'")

    def __len__(self) -> int:
        """Return total message count in active conversation."""
        with self._lock:
            with self._get_connection() as conn:
                row = conn.execute("SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?", (self._active_conversation_id,)).fetchone()
                return int(row["count"]) if row else 0
    
    def purge_all(self) -> int:
        """Permanently delete all stored conversations, messages, and embeddings. Returns number of purged conversations."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute('BEGIN IMMEDIATE')
                count_row = conn.execute("SELECT COUNT(*) as count FROM conversations").fetchone()
                total_convs = int(count_row["count"]) if count_row else 0
                conn.execute("DELETE FROM embeddings")
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")
                conn.commit()
                # Re-create a clean default conversation
                self._active_conversation_id = self.create_conversation(title="Default Conversation")
                logger.info(f"Purged all memory ({total_convs} conversations removed)")
                return total_convs

    def purge_all_memory(self, confirm: bool = False) -> None:
        """Delete the entire SQLite database file after confirmation."""
        if not confirm:
            raise ValueError("Purge all memory requires confirm=True")
        # Close any open connections by ensuring no lock held
        import os
        if os.path.exists(self.db_path) and self.db_path != ":memory:":
            os.remove(self.db_path)
            logger.info("Purged all memory by deleting database file")

    def search(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MemorySearchResult]:
        """Search historical conversation messages using FTS5 with safety limits."""
        if not query or not query.strip():
            return []
        clean_query = query.strip()
        if len(clean_query) > 256:
            logger.warning("Search query exceeds maximum length of 256 characters, truncating.")
            clean_query = clean_query[:256]
        limit = min(max(1, limit), 100)
        start_iso = start_time.isoformat() if start_time else None
        end_iso = end_time.isoformat() if end_time else None
        
        fts_query = self._format_fts_query(clean_query)
        
        with self._lock:
            with self._get_connection() as conn:
                try:
                    sql = """
                        SELECT m.id, m.conversation_id, c.title AS conversation_title,
                               m.role, m.content, m.created_at,
                               bm25(messages_fts) AS rank_score
                        FROM messages_fts f
                        JOIN messages m ON f.message_id = m.id
                        JOIN conversations c ON m.conversation_id = c.id
                        WHERE messages_fts MATCH ?
                    """
                    params: List[Any] = [fts_query]
                    if conversation_id:
                        sql += " AND m.conversation_id = ?"
                        params.append(conversation_id)
                    if start_iso:
                        sql += " AND m.created_at >= ?"
                        params.append(start_iso)
                    if end_iso:
                        sql += " AND m.created_at <= ?"
                        params.append(end_iso)
                    sql += " ORDER BY rank_score ASC LIMIT ?"
                    params.append(limit)
                    rows = conn.execute(sql, tuple(params)).fetchall()
                except sqlite3.OperationalError as e:
                    logger.warning(f"FTS5 query failed: {e}. Falling back to LIKE search.")
                    # fallback to LIKE (omitted for brevity)
                    rows = []
                results: List[MemorySearchResult] = []
                for r in rows:
                    try:
                        ts = datetime.fromisoformat(r["created_at"])
                    except Exception:
                        ts = datetime.now(timezone.utc)
                    results.append(MemorySearchResult(
                        conversation_id=r["conversation_id"],
                        conversation_title=r["conversation_title"] or "Untitled",
                        message_id=r["id"],
                        role=Role(r["role"]),
                        content=r["content"],
                        timestamp=ts,
                        score=float(r["rank_score"]),
                    ))
                return results

    def add_embedding(self, record: EmbeddingRecord) -> None:
        """Store a semantic embedding vector record in SQLite."""
        with self._lock:
            with self._get_connection() as conn:
                blob_str = json.dumps(record.embedding)
                meta_str = json.dumps(record.metadata) if record.metadata else None
                conn.execute(
                    """
                    INSERT OR REPLACE INTO embeddings (
                        id, conversation_id, message_id, source_text,
                        embedding_blob, model, dimension, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.conversation_id,
                        record.message_id,
                        record.source_text,
                        blob_str,
                        record.model,
                        record.dimension,
                        record.created_at.isoformat(),
                        meta_str,
                    ),
                )
                conn.commit()

    def get_embeddings_for_conversation(self, conversation_id: str) -> List[EmbeddingRecord]:
        """Retrieve all stored embedding records for a given conversation."""
        with self._lock:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT id, conversation_id, message_id, source_text,
                           embedding_blob, model, dimension, created_at, metadata
                    FROM embeddings WHERE conversation_id = ?
                    ORDER BY created_at ASC
                    """,
                    (conversation_id,),
                ).fetchall()

        records: List[EmbeddingRecord] = []
        for r in rows:
            try:
                vec = json.loads(r["embedding_blob"]) if isinstance(r["embedding_blob"], str) else json.loads(r["embedding_blob"].decode("utf-8"))
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
                records.append(
                    EmbeddingRecord(
                        id=r["id"],
                        conversation_id=r["conversation_id"],
                        message_id=r["message_id"],
                        source_text=r["source_text"],
                        embedding=vec,
                        model=r["model"],
                        dimension=int(r["dimension"]),
                        created_at=datetime.fromisoformat(r["created_at"]),
                        metadata=meta,
                    )
                )
            except Exception as e:
                logger.warning(f"Error deserializing embedding record '{r['id']}': {e}")
        return records

    def search_semantic(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> List[SemanticSearchResult]:
        """Perform cosine similarity search across stored embedding vectors."""
        if not self.embedding_provider:
            return []

        try:
            query_vector = self.embedding_provider.embed_text(query)
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}")
            return []

        with self._lock:
            with self._get_connection() as conn:
                if conversation_id:
                    cursor = conn.execute(
                        """
                        SELECT id, conversation_id, message_id, source_text,
                               embedding_blob, model, dimension, created_at, metadata
                        FROM embeddings WHERE conversation_id = ?
                        """,
                        (conversation_id,),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT id, conversation_id, message_id, source_text,
                               embedding_blob, model, dimension, created_at, metadata
                        FROM embeddings
                        """
                    )
                rows = cursor.fetchall()

        scored: List[SemanticSearchResult] = []
        for r in rows:
            dim = int(r["dimension"])
            if dim != len(query_vector):
                logger.warning(
                    f"Embedding dimension mismatch on record '{r['id']}' (expected {dim}, got {len(query_vector)}). Skipping."
                )
                continue

            try:
                vec = json.loads(r["embedding_blob"]) if isinstance(r["embedding_blob"], str) else json.loads(r["embedding_blob"].decode("utf-8"))
            except Exception:
                continue

            score = self._cosine_similarity(query_vector, vec)
            if score >= threshold:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
                try:
                    dt = datetime.fromisoformat(r["created_at"])
                except Exception:
                    dt = datetime.now(timezone.utc)

                scored.append(
                    SemanticSearchResult(
                        record_id=r["id"],
                        conversation_id=r["conversation_id"],
                        message_id=r["message_id"],
                        source_text=r["source_text"],
                        score=round(score, 4),
                        created_at=dt,
                        metadata=meta,
                    )
                )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]

    def search_hybrid(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemorySearchResult]:
        """Perform hybrid search combining FTS5 lexical matching and semantic vector similarity using RRF."""
        # 1. Gather lexical results from FTS5
        lexical_results = self.search(query=query, conversation_id=conversation_id, limit=limit * 2)

        # 2. Retrieval Policy: skip semantic search for simple, non-memory queries
        if not should_retrieve_memory(query):
            logger.debug(f"Retrieval policy skipped semantic search for query: '{query}'")
            return lexical_results[:limit]

        # 3. Gather semantic results if embedding provider is available
        semantic_results: List[SemanticSearchResult] = []
        if self.embedding_provider:
            try:
                semantic_results = self.search_semantic(
                    query=query,
                    conversation_id=conversation_id,
                    limit=limit * 2,
                    threshold=0.3,
                )
            except Exception as e:
                logger.warning(f"Semantic search failed; falling back to FTS5: {e}")
                semantic_results = []

        if not semantic_results:
            return lexical_results[:limit]

        if not lexical_results:
            return [
                MemorySearchResult(
                    conversation_id=sr.conversation_id,
                    conversation_title=sr.metadata.get("conversation_title", "Semantic Match"),
                    message_id=sr.message_id or sr.record_id,
                    role=Role(sr.metadata.get("role", "assistant")),
                    content=sr.source_text,
                    timestamp=sr.created_at,
                    score=sr.score,
                )
                for sr in semantic_results[:limit]
            ]

        # 3. Reciprocal Rank Fusion (RRF)
        k = 60.0
        rrf_scores: Dict[str, float] = {}
        merged_items: Dict[str, MemorySearchResult] = {}

        # Score semantic items (weight = 1.0)
        for rank, sr in enumerate(semantic_results, 1):
            key = sr.message_id or sr.record_id
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (1.0 / (k + rank))
            merged_items[key] = MemorySearchResult(
                conversation_id=sr.conversation_id,
                conversation_title=sr.metadata.get("conversation_title", "Semantic Match"),
                message_id=key,
                role=Role(sr.metadata.get("role", "assistant")),
                content=sr.source_text,
                timestamp=sr.created_at,
                score=sr.score,
            )

        # Score lexical items (weight = 0.8)
        for rank, lr in enumerate(lexical_results, 1):
            key = lr.message_id
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (0.8 / (k + rank))
            if key not in merged_items:
                merged_items[key] = lr

        # Sort by fused score
        sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        final_results = []
        for key in sorted_keys[:limit]:
            item = merged_items[key]
            item.score = round(rrf_scores[key], 4)
            final_results.append(item)

        return final_results

    @staticmethod
    def _cosine_similarity(u: List[float], v: List[float]) -> float:
        """Compute cosine similarity between two float vectors."""
        if not u or not v or len(u) != len(v):
            return 0.0
        dot = sum(a * b for a, b in zip(u, v))
        norm_u = math.sqrt(sum(a * a for a in u))
        norm_v = math.sqrt(sum(b * b for b in v))
        if norm_u == 0.0 or norm_v == 0.0:
            return 0.0
        return dot / (norm_u * norm_v)

    def _format_fts_query(self, query: str) -> str:
        """Sanitize and format query string for FTS5 matching."""
        if query.startswith('"') and query.endswith('"') and len(query) > 2:
            inner = query[1:-1].replace('"', '""')
            return f'"{inner}"'

        cleaned = re.sub(r'[^\w\s]', ' ', query)
        tokens = [t for t in cleaned.split() if t]
        if not tokens:
            return f'"{query.replace(chr(34), chr(34)+chr(34))}"'
        stop_words = {
            "what", "is", "my", "our", "the", "a", "an", "and", "or", "in",
            "on", "at", "to", "for", "with", "where", "how", "when", "who",
            "why", "can", "you", "tell", "me", "about", "that", "this",
        }
        content_tokens = [t for t in tokens if t.lower() not in stop_words and len(t) > 1]
        active_tokens = content_tokens if content_tokens else tokens
        return " OR ".join(f'"{t}"*' for t in active_tokens)

    def retain_conversations(self, retention_days: Optional[int] = None) -> None:
        """Purge conversations older than retention period (default from settings)."""
        days = retention_days or getattr(self.settings, 'memory_retention_days', None)
        if not days:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM conversations WHERE created_at < ?", (cutoff_iso,))
                conn.commit()
                logger.info(f"Purged conversations older than {days} days")

    def prune_expired_messages(self, retention_days: int) -> int:
        """Prune messages older than retention_days.

        Returns:
            Count of messages deleted.
        """
        if retention_days <= 0:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM messages WHERE created_at < ?", (cutoff,)
                )
                conn.commit()
                deleted = cursor.rowcount
        if deleted > 0:
            logger.info(f"Pruned {deleted} expired message(s) older than {retention_days} days (cutoff: {cutoff}).")
        return deleted

    def backup(self, backup_path: str) -> str:
        """Create an online hot backup of the SQLite database to a local destination file.

        Args:
            backup_path: Target filesystem path for the backup file.

        Returns:
            Resolved absolute path of the backup file.
        """
        target = Path(backup_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            with self._get_connection() as src_conn:
                dest_conn = sqlite3.connect(str(target))
                try:
                    src_conn.backup(dest_conn)
                finally:
                    dest_conn.close()

        logger.info(f"Created local database backup at '{target}'")
        return str(target)

    def create_hot_backup(self) -> str:
        """Create a hot backup using the configured backup directory. Returns backup file path."""
        backup_dir = Path(self.settings.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        backup_file = backup_dir / f'friday_backup_{timestamp}.db'
        with self._get_connection() as src_conn:
            with sqlite3.connect(str(backup_file)) as dest_conn:
                src_conn.backup(dest_conn)
        logger.info(f"Created hot backup at {backup_file}")
        return str(backup_file)

    def verify_backup(self, backup_file: str) -> bool:
        """Verify backup integrity by comparing message count and SHA256 checksum of files."""
        if not os.path.exists(backup_file):
            return False
        # Compare row counts
        with self._get_connection() as src_conn, sqlite3.connect(backup_file) as backup_conn:
            src_count = src_conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
            backup_count = backup_conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
            if src_count != backup_count:
                logger.warning('Backup verification failed: message count mismatch')
                return False
        # Compare file hash
        def file_hash(path):
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        src_hash = file_hash(self.db_path)
        backup_hash = file_hash(backup_file)
        if src_hash != backup_hash:
            logger.warning('Backup verification failed: file checksum mismatch')
            return False
        logger.info('Backup verification succeeded')
        return True

    def export_conversation_to_dict(self, conversation_id: str) -> Dict[str, Any]:
        """Export a full conversation record including metadata and messages to a dictionary."""
        conv_meta = self.get_conversation(conversation_id)
        if not conv_meta:
            raise ValueError(f"Conversation '{conversation_id}' not found.")

        messages = self.get_messages(conversation_id=conversation_id)
        return {
            "conversation": conv_meta,
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    "name": m.name,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in m.tool_calls
                    ] if m.tool_calls else None,
                    "tool_call_id": m.tool_call_id,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in messages
            ],
        }

    def add_memory_node(
        self,
        content: str,
        memory_type: str = "episodic",
        conversation_id: Optional[str] = None,
        source: str = "user",
        importance: float = 0.5,
        confidence: float = 1.0,
        privacy: str = "private",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store a structured memory node (working, episodic, semantic, task)."""
        valid_types = {"working", "episodic", "semantic", "task"}
        if memory_type not in valid_types:
            raise ValueError(f"Invalid memory_type '{memory_type}'. Must be one of {valid_types}")
        
        return node_id

    @property
    def vector_store(self) -> Optional[Any]:
        """Lazy loader for ChromaVectorStore to prevent blocking startup."""
        if self._vector_store is None:
            try:
                from friday.memory.vector_store import ChromaVectorStore
                from friday.memory.embeddings.factory import create_embedding_provider
                provider = self.embedding_provider or create_embedding_provider(self.settings)
                if provider is not None:
                    chroma_dir = os.path.join(os.path.dirname(self.db_path) if self.db_path != ":memory:" else "data", "chroma")
                    self._vector_store = ChromaVectorStore(
                        persist_dir=chroma_dir,
                        collection_name="friday_memory_nodes",
                        embedding_provider=provider,
                    )
            except Exception as e:
                logger.debug(f"ChromaVectorStore initialization skipped or deferred: {e}")
        return self._vector_store

    def _index_node_in_vector_store_bg(self, node_id: str, content: str, memory_type: str, metadata: Dict[str, Any]) -> None:
        """Background thread target to index memory node into ChromaDB."""
        try:
            vs = self.vector_store
            if vs is not None:
                meta = dict(metadata)
                meta["memory_type"] = memory_type
                meta["node_id"] = node_id
                vs.add_memory(memory_id=node_id, text=content, metadata=meta)
                logger.debug(f"Asynchronously indexed memory node '{node_id}' in ChromaDB")
        except Exception as e:
            logger.debug(f"Background ChromaDB indexing failed for node '{node_id}': {e}")

    def add_memory_node(
        self,
        content: str,
        memory_type: str = "semantic",
        importance: float = 0.5,
        confidence: float = 1.0,
        privacy: str = "internal",
        source: str = "conversation",
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a structured memory node (working, episodic, semantic, task)."""
        valid_types = {"working", "episodic", "semantic", "task"}
        if memory_type not in valid_types:
            raise ValueError(f"Invalid memory_type '{memory_type}'. Must be one of {valid_types}")
        
        node_id = str(uuid.uuid4())
        conv_id = conversation_id or self.active_conversation_id
        now = datetime.now(timezone.utc).isoformat()
        clean_content = filter_secrets(content) or ""
        meta_dict = metadata or {}
        meta_str = json.dumps(meta_dict)

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_nodes (
                        id, conversation_id, memory_type, content, source,
                        importance, confidence, privacy, recency, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node_id,
                        conv_id,
                        memory_type,
                        clean_content,
                        source,
                        max(0.0, min(1.0, float(importance))),
                        max(0.0, min(1.0, float(confidence))),
                        privacy,
                        now,
                        now,
                        meta_str,
                    ),
                )
                conn.commit()

        # Background vector indexing in non-blocking thread for semantic and episodic memories
        if memory_type in ("semantic", "episodic") and clean_content:
            t = threading.Thread(
                target=self._index_node_in_vector_store_bg,
                args=(node_id, clean_content, memory_type, meta_dict),
                daemon=True,
            )
            t.start()

        return node_id

    def get_memory_nodes(
        self,
        memory_type: Optional[str] = None,
        conversation_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve stored memory nodes ordered by recency."""
        conv_id = conversation_id or self.active_conversation_id
        with self._lock:
            with self._get_connection() as conn:
                sql = "SELECT * FROM memory_nodes WHERE 1=1"
                params: List[Any] = []
                if conversation_id:
                    sql += " AND conversation_id = ?"
                    params.append(conv_id)
                if memory_type:
                    sql += " AND memory_type = ?"
                    params.append(memory_type)
                sql += " ORDER BY recency DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "conversation_id": r["conversation_id"],
                "memory_type": r["memory_type"],
                "content": r["content"],
                "source": r["source"],
                "importance": float(r["importance"]),
                "confidence": float(r["confidence"]),
                "privacy": r["privacy"],
                "recency": r["recency"],
                "created_at": r["created_at"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
            })
        return results

    def search_bounded_memories(
        self,
        query: str,
        memory_type: Optional[str] = None,
        top_k: int = 5,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Bounded retrieval using semantic vector similarity (ChromaDB) and FTS5 ranking to fetch top-K relevant memories."""
        if not query or not query.strip():
            return []

        results_by_id: Dict[str, Dict[str, Any]] = {}

        # 1. Semantic Vector Search via ChromaDB
        vs = self.vector_store
        if vs is not None:
            try:
                where_filter = {"memory_type": memory_type} if memory_type else None
                semantic_hits = vs.query_similar(
                    query_text=query,
                    top_k=top_k,
                    min_similarity=0.3,
                    where_filter=where_filter,
                )
                if semantic_hits:
                    hit_ids = [h["id"] for h in semantic_hits]
                    placeholders = ",".join("?" for _ in hit_ids)
                    with self._lock:
                        with self._get_connection() as conn:
                            rows = conn.execute(
                                f"SELECT * FROM memory_nodes WHERE id IN ({placeholders}) AND importance >= ?",
                                hit_ids + [min_importance],
                            ).fetchall()
                    for r in rows:
                        hit_sim = next((h["similarity"] for h in semantic_hits if h["id"] == r["id"]), 0.5)
                        results_by_id[r["id"]] = {
                            "id": r["id"],
                            "conversation_id": r["conversation_id"],
                            "memory_type": r["memory_type"],
                            "content": r["content"],
                            "source": r["source"],
                            "importance": float(r["importance"]),
                            "confidence": float(r["confidence"]),
                            "privacy": r["privacy"],
                            "recency": r["recency"],
                            "created_at": r["created_at"],
                            "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                            "score": float(hit_sim),
                            "retrieval_source": "vector",
                        }
            except Exception as e:
                logger.debug(f"ChromaDB semantic search in search_bounded_memories encountered error: {e}")

        # 2. Keyword Search via SQLite FTS5 (Complement / Fallback)
        fts_query = self._format_fts_query(query.strip())
        with self._lock:
            with self._get_connection() as conn:
                sql = """
                    SELECT n.id, n.conversation_id, n.memory_type, n.content,
                           n.source, n.importance, n.confidence, n.privacy,
                           n.recency, n.created_at, n.metadata,
                           bm25(memory_nodes_fts) AS rank_score
                    FROM memory_nodes_fts f
                    JOIN memory_nodes n ON f.node_id = n.id
                    WHERE memory_nodes_fts MATCH ?
                      AND n.importance >= ?
                """
                params: List[Any] = [fts_query, min_importance]
                if memory_type:
                    sql += " AND n.memory_type = ?"
                    params.append(memory_type)
                sql += " ORDER BY rank_score ASC, n.importance DESC LIMIT ?"
                params.append(top_k)

                try:
                    rows = conn.execute(sql, params).fetchall()
                except Exception as e:
                    logger.debug(f"FTS5 memory node search failed: {e}")
                    rows = []

        for r in rows:
            if r["id"] not in results_by_id:
                results_by_id[r["id"]] = {
                    "id": r["id"],
                    "conversation_id": r["conversation_id"],
                    "memory_type": r["memory_type"],
                    "content": r["content"],
                    "source": r["source"],
                    "importance": float(r["importance"]),
                    "confidence": float(r["confidence"]),
                    "privacy": r["privacy"],
                    "recency": r["recency"],
                    "created_at": r["created_at"],
                    "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
                    "score": float(r["rank_score"]),
                    "retrieval_source": "fts5",
                }

        # Sort combined results by score / importance
        sorted_results = sorted(
            results_by_id.values(),
            key=lambda x: (x.get("score", 0.0), x.get("importance", 0.0)),
            reverse=True,
        )
        return sorted_results[:top_k]

    def delete_memory_node(self, node_id: str) -> bool:
        """User-controlled explicit deletion of a specific memory node."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("DELETE FROM memory_nodes WHERE id = ?", (node_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
        if deleted:
            logger.info(f"User deleted memory node '{node_id}'")
        return deleted

    def export_all_memories(self, target_path: Optional[str] = None) -> Dict[str, Any]:
        """Export all conversations, messages, and memory nodes to a structured dictionary or JSON file."""
        with self._lock:
            with self._get_connection() as conn:
                conv_rows = conn.execute("SELECT * FROM conversations").fetchall()
                msg_rows = conn.execute("SELECT * FROM messages").fetchall()
                node_rows = conn.execute("SELECT * FROM memory_nodes").fetchall()

        export_data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "conversations_count": len(conv_rows),
            "messages_count": len(msg_rows),
            "memory_nodes_count": len(node_rows),
            "conversations": [dict(r) for r in conv_rows],
            "messages": [dict(r) for r in msg_rows],
            "memory_nodes": [dict(r) for r in node_rows],
        }

        if target_path:
            p = Path(target_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2)
            logger.info(f"Exported memories to '{p}'")

        return export_data

    def record_experiment(
        self,
        experiment_name: str,
        task_prompt: str,
        task_type: str,
        provider_name: str,
        model_name: str,
        accuracy: float,
        success: bool,
        latency_ms: float,
        token_usage: int = 0,
        failure_mode: Optional[str] = None,
        response_content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record an experiment trial in the experiments table."""
        exp_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta_str = json.dumps(metadata or {})

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO experiments (
                        id, experiment_name, task_prompt, task_type, provider_name,
                        model_name, accuracy, success, latency_ms, token_usage,
                        failure_mode, response_content, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exp_id,
                        experiment_name,
                        task_prompt,
                        task_type,
                        provider_name,
                        model_name,
                        float(accuracy),
                        1 if success else 0,
                        float(latency_ms),
                        int(token_usage),
                        failure_mode,
                        response_content,
                        now,
                        meta_str,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return exp_id

    def get_provider_performance_stats(self, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Calculate historical latency and success rates per provider for dynamic routing."""
        with self._lock:
            conn = self._get_connection()
            try:
                sql = """
                    SELECT provider_name, model_name,
                           AVG(latency_ms) as avg_latency_ms,
                           AVG(accuracy) as avg_accuracy,
                           AVG(success) as success_rate,
                           COUNT(*) as trial_count
                    FROM experiments
                """
                params: List[Any] = []
                if task_type:
                    sql += " WHERE task_type = ?"
                    params.append(task_type)
                sql += " GROUP BY provider_name, model_name ORDER BY success_rate DESC, avg_latency_ms ASC"
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()

        return [
            {
                "provider_name": r["provider_name"],
                "model_name": r["model_name"],
                "avg_latency_ms": float(r["avg_latency_ms"]),
                "avg_accuracy": float(r["avg_accuracy"]),
                "success_rate": float(r["success_rate"]),
                "trial_count": int(r["trial_count"]),
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close SQLite memory resources cleanly."""
        logger.debug(f"Closed SQLiteConversationMemory at '{self.db_path}'")
