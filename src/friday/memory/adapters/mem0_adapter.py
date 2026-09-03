"""Mem0 Memory Adapter for FRIDAY.

Adapts Mem0's personalized semantic memory into FRIDAY's BaseMemory interface.
FRIDAY remains the authoritative owner of privacy, security, user identity, and
retention. If `mem0ai` is not installed, it degrades gracefully to FRIDAY's
canonical SQLiteConversationMemory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import (
    EmbeddingRecord,
    MemorySearchResult,
    Message,
    Role,
    SemanticSearchResult,
)
from friday.memory.base import BaseMemory
from friday.memory.sqlite import SQLiteConversationMemory

logger = get_logger("memory.mem0_adapter")


class Mem0MemoryAdapter(BaseMemory):
    """Personalized semantic memory adapter wrapping Mem0 behind FRIDAY's BaseMemory."""

    def __init__(
        self,
        user_id: str = "friday_user",
        mem0_config: dict[str, Any] | None = None,
        fallback_memory: BaseMemory | None = None,
    ) -> None:
        self.user_id = user_id
        self.mem0_config = mem0_config or {}
        self.fallback = fallback_memory or SQLiteConversationMemory()
        self._mem0_client: Any | None = None
        self._initialized: bool = False

    @property
    def is_available(self) -> bool:
        """Check if mem0ai package is available."""
        try:
            import mem0  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_mem0(self) -> Any | None:
        """Lazily initialize Mem0 client."""
        if not self._initialized:
            self._initialized = True
            if self.is_available:
                try:
                    from mem0 import Memory

                    self._mem0_client = Memory.from_config(self.mem0_config) if self.mem0_config else Memory()
                    logger.info("Mem0 memory provider initialized successfully.")
                except Exception as e:
                    logger.warning(f"Failed to initialize Mem0: {e}. Falling back to SQLiteConversationMemory.")
                    self._mem0_client = None
        return self._mem0_client

    def add_message(self, message: Message) -> None:
        """Append message to fallback memory and store preferences/facts into Mem0."""
        # Always store in authoritative conversation memory
        self.fallback.add_message(message)

        # Ingest into Mem0 for personalization if available and user/assistant message
        client = self._get_mem0()
        if client and message.content and message.role in (Role.USER, Role.ASSISTANT):
            try:
                # Format for Mem0
                client.add(
                    messages=[{"role": message.role.value, "content": message.content}],
                    user_id=self.user_id,
                )
            except Exception as e:
                logger.debug(f"Mem0 add_message non-fatal error: {e}")

    def get_messages(self) -> list[Message]:
        return self.fallback.get_messages()

    def clear(self) -> None:
        self.fallback.clear()
        client = self._get_mem0()
        if client:
            try:
                client.delete_all(user_id=self.user_id)
            except Exception as e:
                logger.debug(f"Mem0 clear non-fatal error: {e}")

    def get_context_window(self, max_messages: int) -> list[Message]:
        return self.fallback.get_context_window(max_messages)

    def create_conversation(self, title: str | None = None, metadata: dict | None = None) -> str:
        return self.fallback.create_conversation(title=title, metadata=metadata)

    def list_conversations(self, limit: int = 50) -> list[dict]:
        return self.fallback.list_conversations(limit=limit)

    def get_conversation(self, conversation_id: str) -> dict | None:
        return self.fallback.get_conversation(conversation_id)

    def load_conversation(self, conversation_id: str) -> None:
        self.fallback.load_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        return self.fallback.delete_conversation(conversation_id)

    def search(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MemorySearchResult]:
        """Search memory combining SQLite keyword search with Mem0 personalized facts."""
        results: list[MemorySearchResult] = []

        # 1. Search Mem0 semantic personal preferences
        client = self._get_mem0()
        if client:
            try:
                mem0_res = client.search(query=query, user_id=self.user_id, limit=limit)
                if isinstance(mem0_res, list):
                    for item in mem0_res:
                        text = item.get("memory") or item.get("text") or str(item)
                        results.append(
                            MemorySearchResult(
                                conversation_id=conversation_id or "mem0_facts",
                                role=Role.SYSTEM,
                                content=f"[User Memory]: {text}",
                                timestamp=datetime.now(),
                                score=float(item.get("score", 0.9)),
                            )
                        )
            except Exception as e:
                logger.debug(f"Mem0 search non-fatal error: {e}")

        # 2. Search conversation history
        fallback_res = self.fallback.search(
            query=query,
            conversation_id=conversation_id,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
        results.extend(fallback_res)
        return results[:limit]

    def add_embedding(self, record: EmbeddingRecord) -> None:
        self.fallback.add_embedding(record)

    def search_semantic(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> list[SemanticSearchResult]:
        """Search semantic vector memories."""
        client = self._get_mem0()
        if client:
            try:
                mem0_res = client.search(query=query, user_id=self.user_id, limit=limit)
                out = []
                if isinstance(mem0_res, list):
                    for item in mem0_res:
                        text = item.get("memory") or str(item)
                        score = float(item.get("score", 0.9))
                        if score >= threshold:
                            out.append(
                                SemanticSearchResult(
                                    content=f"[User Preference]: {text}",
                                    similarity_score=score,
                                    metadata={"source": "mem0", "user_id": self.user_id},
                                )
                            )
                    if out:
                        return out
            except Exception as e:
                logger.debug(f"Mem0 semantic search non-fatal error: {e}")

        return self.fallback.search_semantic(query=query, conversation_id=conversation_id, limit=limit, threshold=threshold)
