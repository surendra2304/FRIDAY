"""Oracle-backed conversation memory for FRIDAY.

This is the production implementation of :class:`friday.memory.base.BaseMemory`.
It exposes exactly the interface of :class:`friday.memory.sqlite.SQLiteConversationMemory`
so callers (agent, CLI, voice session, learning layer) do not change, and the
SQLite class stays available for explicit local/test use via
:func:`friday.memory.factory.create_memory`.

Storage lives in the ``FRIDAY`` Oracle schema, created by
:func:`friday.core.oracle.ensure_schema`. Differences from the SQLite engine
that are deliberate and unavoidable:

* SQLite FTS5 full-text search does not exist in Oracle. Lexical search uses
  ``LOWER(col) LIKE :token`` over the token set and scores by the fraction of
  tokens matched, so ordering stays "most relevant first" but scores are not
  bm25 values. Oracle Text (``CONTAINS``) needs an index build per table and is
  left as a future optimisation.
* ``backup()`` writes a logical JSON export (the interface returns a path and
  ``verify_backup`` re-reads it) rather than copying a database file.
* ``purge_all_memory()`` truncates rows instead of unlinking a file.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select

from friday.core import oracle
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import (
    EmbeddingRecord,
    MemorySearchResult,
    Message,
    Role,
    SemanticSearchResult,
    ToolCall,
    TrustLevel,
)
from friday.memory.base import BaseMemory
from friday.memory.policies import (
    is_non_informative_tool_notice,
    should_embed_message,
    should_retrieve_memory,
)
from friday.memory.sqlite import filter_secrets

logger = get_logger("memory.oracle")

#: Oracle VARCHAR2 columns reject anything longer; clip rather than fail a write.
_GOAL_MAX = 512
_TITLE_MAX = 512
_NAME_MAX = 255


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _bool(value: Any) -> bool:
    return bool(int(value)) if isinstance(value, (int, float)) else bool(value)


class OracleConversationMemory(BaseMemory):
    """Persistent conversation memory stored in Oracle Autonomous Database."""

    backend = "oracle"

    def __init__(
        self,
        db_path: str | None = None,
        conversation_id: str | None = None,
        max_messages: int = 50,
        embedding_provider: Any | None = None,
        *,
        dsn: str | None = None,
        engine: Any | None = None,
        create_default_conversation: bool = True,
    ) -> None:
        # ``db_path`` is accepted for signature compatibility with
        # SQLiteConversationMemory but never used: Oracle owns the storage.
        if db_path:
            logger.debug("OracleConversationMemory ignores db_path=%r", db_path)
        self.db_path = "oracle://FRIDAY"
        self.max_messages = max(2, max_messages)
        self.embedding_provider = embedding_provider
        self._lock = threading.RLock()
        self._engine = engine
        self._dsn = dsn
        self._vector_store = None
        self.settings = get_settings()
        self._create_default_conversation = create_default_conversation
        self._active_conversation_id = conversation_id

    # ------------------------------------------------------------------
    # Engine / schema
    # ------------------------------------------------------------------
    @property
    def engine(self):
        """Lazily resolve the shared Oracle engine (schema bootstrapped once)."""
        if self._engine is None:
            self._engine = oracle.get_engine(self._dsn)
        return self._engine

    @property
    def active_conversation_id(self) -> str:
        """Resolve the active conversation, creating one on first use.

        Deferred so importing a module that builds a ``FridayAgent`` -- notably
        ``friday.api.server`` -- never opens a database connection.
        """
        if self._active_conversation_id is None:
            if self._create_default_conversation:
                self._active_conversation_id = self._get_or_create_default_conversation()
            else:
                self._active_conversation_id = "default"
        return self._active_conversation_id

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------
    def _get_or_create_default_conversation(self) -> str:
        row = oracle.query_one(
            "SELECT id FROM conversations ORDER BY updated_at DESC, id DESC "
            "FETCH FIRST 1 ROWS ONLY",
            engine=self.engine,
        )
        if row:
            return str(row["id"])
        return self.create_conversation(title="Default Conversation")

    def create_conversation(
        self,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        conv_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        oracle.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, metadata_json) "
            "VALUES (:id, :title, :created, :updated, :meta)",
            {
                "id": conv_id,
                "title": _clip(title or "New Conversation", _TITLE_MAX),
                "created": now,
                "updated": now,
                "meta": _json(metadata or {}),
            },
            engine=self.engine,
        )
        logger.info("Created conversation session '%s' [Title: '%s']", conv_id, title)
        self._active_conversation_id = conv_id
        return conv_id

    _CONVERSATION_SELECT = (
        "SELECT c.id, c.title, c.created_at, c.updated_at, c.metadata_json, "
        "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
        "FROM conversations c"
    )

    @staticmethod
    def _conversation_row(row: Mapping[str, Any]) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        if row.get("metadata_json"):
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row.get("message_count") or 0),
            "metadata": meta,
        }

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = oracle.query_all(
            self._CONVERSATION_SELECT + " ORDER BY c.updated_at DESC, c.id DESC "
            "FETCH FIRST :lim ROWS ONLY",
            {"lim": max(1, int(limit))},
            engine=self.engine,
        )
        return [self._conversation_row(r) for r in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = oracle.query_one(
            self._CONVERSATION_SELECT + " WHERE c.id = :cid",
            {"cid": conversation_id},
            engine=self.engine,
        )
        return self._conversation_row(row) if row else None

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        changed = oracle.execute(
            "UPDATE conversations SET title = :title, updated_at = :now WHERE id = :cid",
            {"title": _clip(new_title, _TITLE_MAX), "now": now, "cid": conversation_id},
            engine=self.engine,
        )
        if changed:
            logger.info("Renamed conversation '%s' to '%s'", conversation_id, new_title)
        return changed > 0

    def load_conversation(self, conversation_id: str) -> None:
        row = oracle.query_one(
            "SELECT id FROM conversations WHERE id = :cid",
            {"cid": conversation_id},
            engine=self.engine,
        )
        if not row:
            raise ValueError(f"Conversation '{conversation_id}' does not exist.")
        self._active_conversation_id = conversation_id
        logger.info("Loaded active conversation session: '%s'", conversation_id)

    def delete_conversation(self, conversation_id: str, confirm: bool = False) -> bool:
        if not confirm:
            raise ValueError("Deletion of conversation requires confirm=True")
        with self._lock:
            with self.engine.begin() as conn:
                from sqlalchemy import text as _text

                for table in ("embeddings", "memory_nodes", "messages"):
                    conn.execute(
                        _text(f"DELETE FROM {table} WHERE conversation_id = :cid"),
                        {"cid": conversation_id},
                    )
                result = conn.execute(
                    _text("DELETE FROM conversations WHERE id = :cid"),
                    {"cid": conversation_id},
                )
                deleted = int(result.rowcount or 0) > 0
        if deleted and self._active_conversation_id == conversation_id:
            self._active_conversation_id = self._get_or_create_default_conversation()
        return deleted

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def add_message(
        self,
        message: Message,
        conversation_id: str | None = None,
        auto_embed: bool = True,
    ) -> None:
        conv_id = conversation_id or self.active_conversation_id
        msg_id = str(uuid.uuid4())
        content = filter_secrets(message.content)

        if message.role == Role.TOOL and content and len(content) > 1000:
            content = content[:1000] + "... [truncated to 1000 chars]"

        if is_non_informative_tool_notice(message):
            logger.info("Not storing a repeat-guard notice as memory: %s", (content or "")[:120])
            return

        last = oracle.query_one(
            "SELECT content FROM messages WHERE conversation_id = :cid "
            "ORDER BY created_at DESC, id DESC FETCH FIRST 1 ROWS ONLY",
            {"cid": conv_id},
            engine=self.engine,
        )
        if last and (last.get("content") or "") == (content or ""):
            logger.debug("Skipping duplicate message insertion.")
            return

        created_at = message.timestamp.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        tool_calls_json = None
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
            tool_calls_json = _json(tc_list)

        meta_dict = dict(message.metadata or {})
        if message.trust_level:
            meta_dict["trust_level"] = message.trust_level.value

        with self._lock:
            with self.engine.begin() as conn:
                from sqlalchemy import text as _text

                existing = conn.execute(
                    _text("SELECT id FROM conversations WHERE id = :cid"),
                    {"cid": conv_id},
                ).fetchone()
                if not existing:
                    conn.execute(
                        _text(
                            "INSERT INTO conversations (id, title, created_at, updated_at, metadata_json) "
                            "VALUES (:id, :title, :created, :updated, :meta)"
                        ),
                        {
                            "id": conv_id,
                            "title": "Auto-created Conversation",
                            "created": created_at,
                            "updated": now,
                            "meta": "{}",
                        },
                    )
                conn.execute(
                    _text(
                        "INSERT INTO messages (id, conversation_id, role, content, name, "
                        "tool_calls_json, tool_call_id, created_at, metadata_json) "
                        "VALUES (:id, :cid, :role, :content, :name, :tool_calls, "
                        ":tool_call_id, :created, :meta)"
                    ),
                    {
                        "id": msg_id,
                        "cid": conv_id,
                        "role": message.role.value,
                        "content": oracle.nullif_empty(content),
                        "name": oracle.nullif_empty(message.name),
                        "tool_calls": tool_calls_json,
                        "tool_call_id": oracle.nullif_empty(message.tool_call_id),
                        "created": created_at,
                        "meta": _json(meta_dict),
                    },
                )
                conn.execute(
                    _text("UPDATE conversations SET updated_at = :now WHERE id = :cid"),
                    {"now": now, "cid": conv_id},
                )
        logger.debug("Saved message '%s' [Role: %s] to conversation '%s'", msg_id, message.role.value, conv_id)

        if auto_embed and self.embedding_provider and should_embed_message(message):
            try:
                digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
                cached = oracle.query_one(
                    "SELECT embedding_json FROM embeddings WHERE source_hash = :hash "
                    "ORDER BY created_at DESC FETCH FIRST 1 ROWS ONLY",
                    {"hash": digest},
                    engine=self.engine,
                )
                existing_emb = None
                if cached and cached.get("embedding_json"):
                    try:
                        existing_emb = json.loads(cached["embedding_json"])
                    except Exception:
                        existing_emb = None
                if isinstance(existing_emb, list) and existing_emb:
                    emb = existing_emb
                    logger.debug("Reused existing semantic embedding from cache.")
                else:
                    emb = self.embedding_provider.embed_text(content)
                self.add_embedding(
                    EmbeddingRecord(
                        id=str(uuid.uuid4()),
                        conversation_id=conv_id,
                        message_id=msg_id,
                        source_text=content,
                        embedding=emb,
                        model=self.embedding_provider.model,
                        dimension=self.embedding_provider.dimension,
                        metadata={"role": message.role.value},
                    )
                )
            except Exception as exc:
                err_str = str(exc)
                if "circuit breaker is open" in err_str or "429" in err_str or "quota" in err_str:
                    logger.debug("Auto-embedding skipped: %s", err_str)
                else:
                    logger.debug("Auto-embedding message failed: %s", err_str)

    _MESSAGE_COLUMNS = (
        "id, conversation_id, role, content, name, tool_calls_json, tool_call_id, "
        "created_at, metadata_json"
    )

    def _row_to_message(self, row: Mapping[str, Any]) -> Message:
        tool_calls = None
        if row.get("tool_calls_json"):
            try:
                tc_data = json.loads(row["tool_calls_json"])
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
            except Exception as exc:
                logger.warning("Failed to deserialize tool_calls for message %s: %s", row.get("id"), exc)

        try:
            ts = datetime.fromisoformat(row["created_at"])
        except Exception:
            ts = datetime.now(timezone.utc)

        try:
            role = Role(row["role"])
        except Exception:
            role = Role.USER

        msg_meta: dict[str, Any] = {}
        trust = TrustLevel.TRUSTED_USER
        if row.get("metadata_json"):
            try:
                msg_meta = json.loads(row["metadata_json"])
                if isinstance(msg_meta, dict) and "trust_level" in msg_meta:
                    t_val = msg_meta["trust_level"]
                    if t_val in TrustLevel._value2member_map_:
                        trust = TrustLevel(t_val)
            except Exception:
                pass

        return Message(
            role=role,
            content=row.get("content") or "",
            name=row.get("name"),
            tool_calls=tool_calls,
            tool_call_id=row.get("tool_call_id"),
            timestamp=ts,
            trust_level=trust,
            metadata=msg_meta,
        )

    def get_messages(self, conversation_id: str | None = None) -> list[Message]:
        conv_id = conversation_id or self.active_conversation_id
        rows = oracle.query_all(
            f"SELECT {self._MESSAGE_COLUMNS} FROM messages WHERE conversation_id = :cid "
            "ORDER BY created_at ASC, id ASC",
            {"cid": conv_id},
            engine=self.engine,
        )
        return [self._row_to_message(r) for r in rows]

    def get_context_window(
        self,
        max_messages: int = 50,
        conversation_id: str | None = None,
        max_turns: int | None = None,
        max_tokens: int = 3000,
    ) -> list[Message]:
        if max_messages <= 0:
            return []
        conv_id = conversation_id or self.active_conversation_id
        if max_turns is not None and max_turns > 0:
            effective_limit = min(max_messages, max_turns * 2)
        else:
            effective_limit = max_messages

        rows = oracle.query_all(
            f"SELECT {self._MESSAGE_COLUMNS} FROM ("
            f"  SELECT {self._MESSAGE_COLUMNS} FROM messages WHERE conversation_id = :cid "
            "   ORDER BY created_at DESC, id DESC FETCH FIRST :lim ROWS ONLY"
            ") ORDER BY created_at ASC, id ASC",
            {"cid": conv_id, "lim": int(effective_limit)},
            engine=self.engine,
        )
        messages = [self._row_to_message(r) for r in rows]

        if max_tokens > 0 and messages:
            char_budget = max_tokens * 4
            running_chars = 0
            trimmed_reversed: list[Message] = []
            for msg in reversed(messages):
                msg_len = len(msg.content or "") + 100
                if running_chars + msg_len > char_budget and trimmed_reversed:
                    break
                trimmed_reversed.append(msg)
                running_chars += msg_len
            messages = list(reversed(trimmed_reversed))
        return messages

    def clear(self, conversation_id: str | None = None, confirm: bool = False) -> None:
        if not confirm:
            raise ValueError("Clear memory requires confirm=True")
        conv_id = conversation_id or self.active_conversation_id
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.engine.begin() as conn:
                from sqlalchemy import text as _text

                conn.execute(
                    _text("DELETE FROM messages WHERE conversation_id = :cid"),
                    {"cid": conv_id},
                )
                conn.execute(
                    _text("UPDATE conversations SET updated_at = :now WHERE id = :cid"),
                    {"now": now, "cid": conv_id},
                )
        logger.debug("Cleared messages in conversation '%s'", conv_id)

    def __len__(self) -> int:
        value = oracle.scalar(
            "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = :cid",
            {"cid": self.active_conversation_id},
            engine=self.engine,
            default=0,
        )
        return int(value or 0)

    def purge_all(self) -> int:
        with self._lock:
            with self.engine.begin() as conn:
                from sqlalchemy import text as _text

                total_convs = int(
                    conn.execute(_text("SELECT COUNT(*) FROM conversations")).scalar() or 0
                )
                for table in ("embeddings", "memory_nodes", "messages", "conversations"):
                    conn.execute(_text(f"DELETE FROM {table}"))
        self._active_conversation_id = self.create_conversation(title="Default Conversation")
        logger.info("Purged all memory (%d conversations removed)", total_convs)
        return total_convs

    def purge_all_memory(self, confirm: bool = False) -> None:
        if not confirm:
            raise ValueError("Purge all memory requires confirm=True")
        self.purge_all()

    # ------------------------------------------------------------------
    # Lexical search (SQLite FTS5 replacement)
    # ------------------------------------------------------------------
    _STOP_WORDS = {
        "what", "is", "my", "our", "the", "a", "an", "and", "or", "in",
        "on", "at", "to", "for", "with", "where", "how", "when", "who",
        "why", "can", "you", "tell", "me", "about", "that", "this",
    }

    def _search_tokens(self, query: str) -> list[str]:
        cleaned = re.sub(r"[^\w\s]", " ", query)
        tokens = [t for t in cleaned.split() if t]
        content_tokens = [t for t in tokens if t.lower() not in self._STOP_WORDS and len(t) > 1]
        return (content_tokens or tokens)[:12]

    def _like_clause(self, tokens: Sequence[str], column: str) -> tuple[str, dict[str, Any]]:
        clauses = []
        params: dict[str, Any] = {}
        for index, token in enumerate(tokens):
            key = f"tok{index}"
            clauses.append(f"LOWER({column}) LIKE :{key} ESCAPE '\\'")
            params[key] = f"%{token.lower()}%"
        return "(" + " OR ".join(clauses) + ")", params

    @staticmethod
    def _like_score(content: str | None, tokens: Sequence[str]) -> float:
        if not tokens:
            return 0.0
        lowered = (content or "").lower()
        matched = sum(1 for token in tokens if token.lower() in lowered)
        return round(matched / len(tokens), 4)

    def search(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MemorySearchResult]:
        if not query or not query.strip():
            return []
        clean_query = query.strip()
        if len(clean_query) > 256:
            logger.warning("Search query exceeds maximum length of 256 characters, truncating.")
            clean_query = clean_query[:256]
        limit = min(max(1, limit), 100)
        tokens = self._search_tokens(clean_query)
        if not tokens:
            return []

        where, params = self._like_clause(tokens, "m.content")
        sql = (
            "SELECT m.id, m.conversation_id, c.title AS conversation_title, m.role, "
            "m.content, m.created_at FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.id "
            f"WHERE {where}"
        )
        if conversation_id:
            sql += " AND m.conversation_id = :conv"
            params["conv"] = conversation_id
        if start_time:
            sql += " AND m.created_at >= :start"
            params["start"] = start_time.isoformat()
        if end_time:
            sql += " AND m.created_at <= :end"
            params["end"] = end_time.isoformat()
        sql += " ORDER BY m.created_at DESC FETCH FIRST :lim ROWS ONLY"
        params["lim"] = limit

        rows = oracle.query_all(sql, params, engine=self.engine)
        results: list[MemorySearchResult] = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["created_at"])
            except Exception:
                ts = datetime.now(timezone.utc)
            try:
                role = Role(row["role"])
            except Exception:
                role = Role.ASSISTANT
            results.append(
                MemorySearchResult(
                    conversation_id=row["conversation_id"],
                    conversation_title=row["conversation_title"] or "Untitled",
                    message_id=row["id"],
                    role=role,
                    content=row["content"] or "",
                    timestamp=ts,
                    score=self._like_score(row["content"], tokens),
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def add_embedding(self, record: EmbeddingRecord) -> None:
        digest = hashlib.sha256((record.source_text or "").encode("utf-8")).hexdigest()
        oracle.execute(
            """
            MERGE INTO embeddings t
            USING (SELECT :id AS id FROM DUAL) s
            ON (t.id = s.id)
            WHEN MATCHED THEN UPDATE SET
                t.conversation_id = :conv,
                t.message_id = :mid,
                t.source_text = :src,
                t.source_hash = :hash,
                t.embedding_json = :emb,
                t.model = :model,
                t.dimension = :dim,
                t.created_at = :created,
                t.metadata_json = :meta
            WHEN NOT MATCHED THEN INSERT
                (id, conversation_id, message_id, source_text, source_hash,
                 embedding_json, model, dimension, created_at, metadata_json)
            VALUES
                (:id, :conv, :mid, :src, :hash, :emb, :model, :dim, :created, :meta)
            """,
            {
                "id": record.id,
                "conv": record.conversation_id,
                "mid": record.message_id,
                "src": record.source_text,
                "hash": digest,
                "emb": _json(record.embedding),
                "model": record.model,
                "dim": int(record.dimension),
                "created": record.created_at.isoformat(),
                "meta": _json(record.metadata) if record.metadata else None,
            },
            engine=self.engine,
        )

    _EMBEDDING_COLUMNS = (
        "id, conversation_id, message_id, source_text, embedding_json, model, "
        "dimension, created_at, metadata_json"
    )

    def get_embeddings_for_conversation(self, conversation_id: str) -> list[EmbeddingRecord]:
        rows = oracle.query_all(
            f"SELECT {self._EMBEDDING_COLUMNS} FROM embeddings WHERE conversation_id = :cid "
            "ORDER BY created_at ASC",
            {"cid": conversation_id},
            engine=self.engine,
        )
        records: list[EmbeddingRecord] = []
        for row in rows:
            try:
                vector = json.loads(row["embedding_json"]) if row["embedding_json"] else []
                meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                records.append(
                    EmbeddingRecord(
                        id=row["id"],
                        conversation_id=row["conversation_id"],
                        message_id=row["message_id"],
                        source_text=row["source_text"] or "",
                        embedding=vector,
                        model=row["model"],
                        dimension=int(row["dimension"] or 0),
                        created_at=datetime.fromisoformat(row["created_at"]),
                        metadata=meta,
                    )
                )
            except Exception as exc:
                logger.warning("Error deserializing embedding record '%s': %s", row.get("id"), exc)
        return records

    def search_semantic(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> list[SemanticSearchResult]:
        if not self.embedding_provider:
            return []
        try:
            query_vector = self.embedding_provider.embed_text(query)
        except Exception as exc:
            logger.warning("Failed to generate query embedding: %s", exc)
            return []

        sql = (
            f"SELECT {self._EMBEDDING_COLUMNS} FROM embeddings"
        )
        params: dict[str, Any] = {}
        if conversation_id:
            sql += " WHERE conversation_id = :cid"
            params["cid"] = conversation_id
        rows = oracle.query_all(sql, params, engine=self.engine)

        scored: list[SemanticSearchResult] = []
        for row in rows:
            dim = int(row["dimension"] or 0)
            if dim != len(query_vector):
                continue
            try:
                vector = json.loads(row["embedding_json"]) if row["embedding_json"] else []
            except Exception:
                continue
            if not vector:
                continue
            score = self._cosine_similarity(query_vector, vector)
            if score >= threshold:
                try:
                    meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                except Exception:
                    meta = {}
                try:
                    dt = datetime.fromisoformat(row["created_at"])
                except Exception:
                    dt = datetime.now(timezone.utc)
                scored.append(
                    SemanticSearchResult(
                        record_id=row["id"],
                        conversation_id=row["conversation_id"],
                        message_id=row["message_id"],
                        source_text=row["source_text"] or "",
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
        conversation_id: str | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        lexical_results = self.search(query=query, conversation_id=conversation_id, limit=limit * 2)

        if not should_retrieve_memory(query):
            logger.debug("Retrieval policy skipped semantic search for query: '%s'", query)
            return lexical_results[:limit]

        semantic_results: list[SemanticSearchResult] = []
        if self.embedding_provider:
            try:
                semantic_results = self.search_semantic(
                    query=query,
                    conversation_id=conversation_id,
                    limit=limit * 2,
                    threshold=0.3,
                )
            except Exception as exc:
                logger.warning("Semantic search failed; falling back to lexical: %s", exc)
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

        k = 60.0
        rrf_scores: dict[str, float] = {}
        merged_items: dict[str, MemorySearchResult] = {}

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

        for rank, lr in enumerate(lexical_results, 1):
            key = lr.message_id
            rrf_scores[key] = rrf_scores.get(key, 0.0) + (0.8 / (k + rank))
            merged_items.setdefault(key, lr)

        ordered = sorted(rrf_scores, key=lambda key: rrf_scores[key], reverse=True)
        final: list[MemorySearchResult] = []
        for key in ordered[:limit]:
            item = merged_items[key]
            item.score = round(rrf_scores[key], 4)
            final.append(item)
        return final

    @staticmethod
    def _cosine_similarity(u: list[float], v: list[float]) -> float:
        if not u or not v or len(u) != len(v):
            return 0.0
        dot = sum(a * b for a, b in zip(u, v))
        norm_u = math.sqrt(sum(a * a for a in u))
        norm_v = math.sqrt(sum(b * b for b in v))
        if norm_u == 0.0 or norm_v == 0.0:
            return 0.0
        return dot / (norm_u * norm_v)

    # ------------------------------------------------------------------
    # Retention / export
    # ------------------------------------------------------------------
    def retain_conversations(self, retention_days: int | None = None) -> None:
        days = retention_days or getattr(self.settings, "memory_retention_days", None)
        if not days:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock, self.engine.begin() as conn:
            from sqlalchemy import text as _text

            stale = [
                row[0]
                for row in conn.execute(
                    _text("SELECT id FROM conversations WHERE created_at < :cutoff"),
                    {"cutoff": cutoff},
                ).fetchall()
            ]
            for conv_id in stale:
                for table in ("embeddings", "memory_nodes", "messages"):
                    conn.execute(
                        _text(f"DELETE FROM {table} WHERE conversation_id = :cid"),
                        {"cid": conv_id},
                    )
                conn.execute(
                    _text("DELETE FROM conversations WHERE id = :cid"), {"cid": conv_id}
                )
        logger.info("Purged %d conversation(s) older than %d days", len(stale), days)

    def prune_expired_messages(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        deleted = oracle.execute(
            "DELETE FROM messages WHERE created_at < :cutoff",
            {"cutoff": cutoff},
            engine=self.engine,
        )
        if deleted > 0:
            logger.info(
                "Pruned %d expired message(s) older than %d days (cutoff: %s).",
                deleted,
                retention_days,
                cutoff,
            )
        return deleted

    def backup(self, backup_path: str) -> str:
        """Write a logical JSON export of the FRIDAY memory schema.

        Oracle hot backups belong to RMAN/Data Pump, which FRIDAY does not own.
        The contract callers rely on is "produce a restorable artifact at this
        path and let verify_backup() check it", so the export is JSON and
        ``verify_backup`` re-reads it.
        """
        target = Path(backup_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.export_all_memories()
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        logger.info("Created memory export at '%s'", target)
        return str(target)

    def create_hot_backup(self) -> str:
        backup_dir = Path(self.settings.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return self.backup(str(backup_dir / f"friday_memory_{timestamp}.json"))

    def verify_backup(self, backup_file: str) -> bool:
        if not os.path.exists(backup_file):
            return False
        try:
            with open(backup_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            backup_count = int(payload.get("messages_count", -1))
            live_count = int(oracle.scalar("SELECT COUNT(*) FROM messages", engine=self.engine, default=0) or 0)
        except Exception as exc:
            logger.warning("Backup verification failed: %s", exc)
            return False
        if backup_count != live_count:
            logger.warning(
                "Backup verification failed: message count mismatch (%s != %s)",
                backup_count,
                live_count,
            )
            return False
        logger.info("Backup verification succeeded")
        return True

    def export_conversation_to_dict(self, conversation_id: str) -> dict[str, Any]:
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

    def export_all_memories(self, target_path: str | None = None) -> dict[str, Any]:
        conversations = oracle.query_all("SELECT * FROM conversations", engine=self.engine)
        messages = oracle.query_all("SELECT * FROM messages", engine=self.engine)
        nodes = oracle.query_all("SELECT * FROM memory_nodes", engine=self.engine)
        export_data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "backend": "oracle",
            "schema": oracle.SCHEMA_OWNER,
            "conversations_count": len(conversations),
            "messages_count": len(messages),
            "memory_nodes_count": len(nodes),
            "conversations": conversations,
            "messages": messages,
            "memory_nodes": nodes,
        }
        if target_path:
            path = Path(target_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(export_data, handle, indent=2)
            logger.info("Exported memories to '%s'", path)
        return export_data

    # ------------------------------------------------------------------
    # Structured memory nodes
    # ------------------------------------------------------------------
    @property
    def vector_store(self) -> Any | None:
        """Lazy ChromaDB vector store (optional dependency, disk-backed)."""
        if self._vector_store is None:
            try:
                from friday.memory.embeddings.factory import create_embedding_provider
                from friday.memory.vector_store import ChromaVectorStore

                provider = self.embedding_provider or create_embedding_provider(self.settings)
                if provider is not None:
                    chroma_dir = os.getenv("FRIDAY_VECTOR_STORE_DIR", os.path.join("data", "chroma"))
                    self._vector_store = ChromaVectorStore(
                        persist_dir=chroma_dir,
                        collection_name="friday_memory_nodes",
                        embedding_provider=provider,
                    )
            except Exception as exc:
                logger.debug("ChromaVectorStore initialization skipped or deferred: %s", exc)
        return self._vector_store

    def _index_node_in_vector_store_bg(
        self, node_id: str, content: str, memory_type: str, metadata: dict[str, Any]
    ) -> None:
        try:
            store = self.vector_store
            if store is not None:
                meta = dict(metadata)
                meta["memory_type"] = memory_type
                meta["node_id"] = node_id
                store.add_memory(memory_id=node_id, text=content, metadata=meta)
                logger.debug("Asynchronously indexed memory node '%s' in ChromaDB", node_id)
        except Exception as exc:
            logger.debug("Background ChromaDB indexing failed for node '%s': %s", node_id, exc)

    def add_memory_node(
        self,
        content: str,
        memory_type: str = "semantic",
        importance: float = 0.5,
        confidence: float = 1.0,
        privacy: str = "internal",
        source: str = "conversation",
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        valid_types = {"working", "episodic", "semantic", "task"}
        if memory_type not in valid_types:
            raise ValueError(f"Invalid memory_type '{memory_type}'. Must be one of {valid_types}")

        node_id = str(uuid.uuid4())
        conv_id = conversation_id or self.active_conversation_id
        now = datetime.now(timezone.utc).isoformat()
        clean_content = filter_secrets(content) or ""
        meta_dict = metadata or {}

        oracle.execute(
            "INSERT INTO memory_nodes (id, conversation_id, memory_type, content, source, "
            "importance, confidence, privacy, recency, created_at, metadata_json) "
            "VALUES (:id, :cid, :mtype, :content, :source, :importance, :confidence, "
            ":privacy, :recency, :created, :meta)",
            {
                "id": node_id,
                "cid": conv_id,
                "mtype": memory_type,
                "content": clean_content or None,
                "source": source,
                "importance": max(0.0, min(1.0, float(importance))),
                "confidence": max(0.0, min(1.0, float(confidence))),
                "privacy": privacy,
                "recency": now,
                "created": now,
                "meta": _json(meta_dict),
            },
            engine=self.engine,
        )

        if memory_type in ("semantic", "episodic") and clean_content:
            threading.Thread(
                target=self._index_node_in_vector_store_bg,
                args=(node_id, clean_content, memory_type, meta_dict),
                daemon=True,
            ).start()
        return node_id

    @staticmethod
    def _node_row(row: Mapping[str, Any]) -> dict[str, Any]:
        try:
            meta = json.loads(row["metadata_json"]) if row.get("metadata_json") else {}
        except Exception:
            meta = {}
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "memory_type": row["memory_type"],
            "content": row["content"] or "",
            "source": row["source"],
            "importance": float(row["importance"] or 0.0),
            "confidence": float(row["confidence"] or 0.0),
            "privacy": row["privacy"],
            "recency": row["recency"],
            "created_at": row["created_at"],
            "metadata": meta,
        }

    def get_memory_nodes(
        self,
        memory_type: str | None = None,
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conv_id = conversation_id or self.active_conversation_id
        sql = "SELECT * FROM memory_nodes WHERE 1 = 1"
        params: dict[str, Any] = {}
        if conversation_id:
            sql += " AND conversation_id = :cid"
            params["cid"] = conv_id
        if memory_type:
            sql += " AND memory_type = :mtype"
            params["mtype"] = memory_type
        sql += " ORDER BY recency DESC FETCH FIRST :lim ROWS ONLY"
        params["lim"] = max(1, int(limit))
        rows = oracle.query_all(sql, params, engine=self.engine)
        return [self._node_row(r) for r in rows]

    def search_bounded_memories(
        self,
        query: str,
        memory_type: str | None = None,
        top_k: int = 5,
        min_importance: float = 0.0,
    ) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []
        results_by_id: dict[str, dict[str, Any]] = {}

        store = self.vector_store
        if store is not None:
            try:
                where_filter = {"memory_type": memory_type} if memory_type else None
                hits = store.query_similar(
                    query_text=query,
                    top_k=top_k,
                    min_similarity=0.3,
                    where_filter=where_filter,
                )
                if hits:
                    hit_ids = [h["id"] for h in hits]
                    params: dict[str, Any] = {"min_importance": min_importance}
                    binds = []
                    for index, hit in enumerate(hit_ids):
                        key = f"id{index}"
                        binds.append(f":{key}")
                        params[key] = hit
                    rows = oracle.query_all(
                        "SELECT * FROM memory_nodes WHERE id IN ("
                        + ", ".join(binds)
                        + ") AND importance >= :min_importance",
                        params,
                        engine=self.engine,
                    )
                    for row in rows:
                        sim = next((h["similarity"] for h in hits if h["id"] == row["id"]), 0.5)
                        entry = self._node_row(row)
                        entry["score"] = float(sim)
                        entry["retrieval_source"] = "vector"
                        results_by_id[row["id"]] = entry
            except Exception as exc:
                logger.debug("Vector search in search_bounded_memories failed: %s", exc)

        tokens = self._search_tokens(query)
        if tokens:
            where, params = self._like_clause(tokens, "n.content")
            sql = (
                "SELECT n.* FROM memory_nodes n WHERE "
                + where
                + " AND n.importance >= :min_importance"
            )
            params["min_importance"] = min_importance
            if memory_type:
                sql += " AND n.memory_type = :mtype"
                params["mtype"] = memory_type
            sql += " ORDER BY n.importance DESC, n.recency DESC FETCH FIRST :lim ROWS ONLY"
            params["lim"] = max(1, int(top_k))
            for row in oracle.query_all(sql, params, engine=self.engine):
                if row["id"] not in results_by_id:
                    entry = self._node_row(row)
                    entry["score"] = self._like_score(row["content"], tokens)
                    entry["retrieval_source"] = "lexical"
                    results_by_id[row["id"]] = entry

        ordered = sorted(
            results_by_id.values(),
            key=lambda x: (x.get("score", 0.0), x.get("importance", 0.0)),
            reverse=True,
        )
        return ordered[:top_k]

    def delete_memory_node(self, node_id: str) -> bool:
        deleted = oracle.execute(
            "DELETE FROM memory_nodes WHERE id = :id", {"id": node_id}, engine=self.engine
        )
        if deleted:
            logger.info("User deleted memory node '%s'", node_id)
        return deleted > 0

    # ------------------------------------------------------------------
    # Experiments and traces
    # ------------------------------------------------------------------
    def record_experiment(
        self,
        experiment_name: str,
        task_prompt: str,
        task_type: str,
        provider_name: str,
        model_name: str,
        accuracy: float | None,
        success: bool,
        latency_ms: float | None,
        token_usage: int = 0,
        failure_mode: str | None = None,
        response_content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        exp_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        oracle.execute(
            "INSERT INTO experiments (id, experiment_name, task_prompt, task_type, "
            "provider_name, model_name, accuracy, success, latency_ms, token_usage, "
            "failure_mode, response_content, created_at, metadata_json) "
            "VALUES (:id, :name, :prompt, :ttype, :provider, :model, :accuracy, :success, "
            ":latency, :tokens, :failure, :response, :created, :meta)",
            {
                "id": exp_id,
                "name": experiment_name,
                "prompt": task_prompt,
                "ttype": task_type,
                "provider": provider_name,
                "model": model_name,
                "accuracy": None if accuracy is None else float(accuracy),
                "success": 1 if success else 0,
                "latency": None if latency_ms is None else float(latency_ms),
                "tokens": int(token_usage),
                "failure": failure_mode,
                "response": response_content,
                "created": now,
                "meta": _json(metadata or {}),
            },
            engine=self.engine,
        )
        return exp_id

    def get_provider_performance_stats(self, task_type: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT provider_name, model_name, AVG(latency_ms) AS avg_latency_ms, "
            "AVG(accuracy) AS avg_accuracy, AVG(success) AS success_rate, "
            "COUNT(*) AS trial_count FROM experiments"
        )
        params: dict[str, Any] = {}
        if task_type:
            sql += " WHERE task_type = :ttype"
            params["ttype"] = task_type
        sql += " GROUP BY provider_name, model_name ORDER BY success_rate DESC, avg_latency_ms ASC"
        rows = oracle.query_all(sql, params, engine=self.engine)
        return [
            {
                "provider_name": row["provider_name"],
                "model_name": row["model_name"],
                "avg_latency_ms": float(row["avg_latency_ms"] or 0.0),
                "avg_accuracy": float(row["avg_accuracy"] or 0.0),
                "success_rate": float(row["success_rate"] or 0.0),
                "trial_count": int(row["trial_count"] or 0),
            }
            for row in rows
        ]

    def log_execution_trace(
        self,
        goal: str,
        tools_used: list[str] | None = None,
        models_used: list[str] | None = None,
        provider: str | None = None,
        latency_ms: float = 0.0,
        success: bool = True,
        task_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> str:
        tid = trace_id or f"tr_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        oracle.execute(
            "INSERT INTO learning_traces (id, goal, task_type, tools_used_json, "
            "models_used_json, provider, latency_ms, success, error_message, "
            "created_at, metadata_json) VALUES (:id, :goal, :ttype, :tools, :models, "
            ":provider, :latency, :success, :error, :created, :meta)",
            {
                "id": tid,
                "goal": _clip(goal, _GOAL_MAX),
                "ttype": task_type or "general",
                "tools": _json(tools_used or []),
                "models": _json(models_used or []),
                "provider": provider or "default",
                "latency": float(latency_ms),
                "success": 1 if success else 0,
                "error": error_message,
                "created": now,
                "meta": _json(metadata or {}),
            },
            engine=self.engine,
        )
        return tid

    def get_execution_traces(
        self,
        limit: int = 100,
        task_type: str | None = None,
        provider: str | None = None,
        success_only: bool | None = None,
        goal_query: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM learning_traces WHERE 1 = 1"
        params: dict[str, Any] = {}
        if task_type:
            sql += " AND task_type = :ttype"
            params["ttype"] = task_type
        if provider:
            sql += " AND provider = :provider"
            params["provider"] = provider
        if success_only is not None:
            sql += " AND success = :success"
            params["success"] = 1 if success_only else 0
        if goal_query:
            sql += " AND LOWER(goal) LIKE :goal"
            params["goal"] = f"%{goal_query.lower()}%"
        sql += " ORDER BY created_at DESC FETCH FIRST :lim ROWS ONLY"
        params["lim"] = max(1, int(limit))

        traces = []
        for row in oracle.query_all(sql, params, engine=self.engine):
            traces.append(
                {
                    "trace_id": row["id"],
                    "goal": row["goal"],
                    "task_type": row["task_type"],
                    "tools_used": json.loads(row["tools_used_json"] or "[]"),
                    "models_used": json.loads(row["models_used_json"] or "[]"),
                    "provider": row["provider"],
                    "latency_ms": float(row["latency_ms"] or 0.0),
                    "success": _bool(row["success"]),
                    "error_message": row["error_message"],
                    "created_at": row["created_at"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                }
            )
        return traces

    def get_trace_stats(self) -> dict[str, Any]:
        row = oracle.query_one(
            "SELECT COUNT(*) AS total_traces, "
            "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_traces, "
            "AVG(latency_ms) AS avg_latency_ms FROM learning_traces",
            engine=self.engine,
        ) or {}
        total = int(row.get("total_traces") or 0)
        successes = int(row.get("successful_traces") or 0)
        avg_lat = float(row.get("avg_latency_ms") or 0.0)
        return {
            "total_traces": total,
            "successful_traces": successes,
            "failed_traces": total - successes,
            "success_rate": (successes / total) if total > 0 else 0.0,
            "avg_latency_ms": avg_lat,
        }

    def close(self) -> None:
        """Release per-instance resources; the shared engine stays pooled."""
        logger.debug("Closed OracleConversationMemory for conversation '%s'", self._active_conversation_id or 'default')


__all__ = ["OracleConversationMemory"]
