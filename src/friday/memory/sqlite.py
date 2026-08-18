"""SQLite-backed conversation memory with ACID persistence and conversation isolation."""

import json
import math
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from friday.core.logging import get_logger
from friday.core.types import EmbeddingRecord, MemorySearchResult, Message, Role, SemanticSearchResult, ToolCall
from friday.memory.base import BaseMemory

logger = get_logger("memory.sqlite")


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
        conn.execute("PRAGMA busy_timeout = 20000;")
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA cache_size = -64000;")
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

        try:
            role = Role(row["role"])
        except Exception:
            role = Role.USER

        return Message(
            role=role,
            content=row["content"] or "",
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

    def search(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        limit: int = 10,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MemorySearchResult]:
        """Search historical conversation messages using full-text search with relevance ranking."""
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        limit = max(1, limit)
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
                    if not rows and not (clean_query.startswith('"') and clean_query.endswith('"')):
                        # Fallback to OR query for natural language questions with stop words
                        tokens = [t for t in re.sub(r'[^\w\s]', ' ', clean_query).split() if len(t) > 2]
                        if len(tokens) > 1:
                            or_query = " OR ".join(f'"{t}"*' for t in tokens)
                            or_params = [or_query] + params[1:]
                            rows = conn.execute(sql, tuple(or_params)).fetchall()
                except sqlite3.OperationalError as e:
                    logger.warning(f"FTS5 query failed for '{fts_query}' ({e}). Falling back to LIKE search.")
                    sql = """
                        SELECT m.id, m.conversation_id, c.title AS conversation_title,
                               m.role, m.content, m.created_at,
                               1.0 AS rank_score
                        FROM messages m
                        JOIN conversations c ON m.conversation_id = c.id
                        WHERE m.content LIKE ?
                    """
                    params = [f"%{clean_query}%"]
                    if conversation_id:
                        sql += " AND m.conversation_id = ?"
                        params.append(conversation_id)
                    if start_iso:
                        sql += " AND m.created_at >= ?"
                        params.append(start_iso)
                    if end_iso:
                        sql += " AND m.created_at <= ?"
                        params.append(end_iso)
                    sql += " ORDER BY m.created_at DESC LIMIT ?"
                    params.append(limit)
                    rows = conn.execute(sql, tuple(params)).fetchall()

                results: List[MemorySearchResult] = []
                for r in rows:
                    try:
                        ts = datetime.fromisoformat(r["created_at"])
                    except Exception:
                        ts = datetime.now(timezone.utc)

                    results.append(
                        MemorySearchResult(
                            conversation_id=r["conversation_id"],
                            conversation_title=r["conversation_title"] or "Untitled",
                            message_id=r["id"],
                            role=Role(r["role"]),
                            content=r["content"],
                            timestamp=ts,
                            score=float(r["rank_score"]),
                        )
                    )
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

        # 2. Gather semantic results if embedding provider is available
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
        tokens = cleaned.split()
        if not tokens:
            return f'"{query.replace(chr(34), chr(34)+chr(34))}"'
        return " ".join(f'"{t}"*' for t in tokens)

    def purge_all(self) -> int:
        """Permanently delete all conversations and messages, resetting database storage.

        Returns:
            Count of conversations purged.
        """
        with self._lock:
            with self._get_connection() as conn:
                count_row = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
                total_convs = count_row[0] if count_row else 0
                conn.execute("DELETE FROM messages")
                conn.execute("DELETE FROM conversations")
                try:
                    conn.execute("DELETE FROM messages_fts")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
                conn.execute("VACUUM")

        self._active_conversation_id = self.create_conversation(title="Default Conversation")
        logger.warning(f"Purged all persistent conversation memory ({total_convs} conversation(s) deleted).")
        return total_convs

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
