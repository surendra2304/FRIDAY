"""In-memory sliding window conversation buffer memory."""

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

logger = get_logger("memory.in_memory")


class InMemoryConversationMemory(BaseMemory):
    """Simple, fast in-memory conversation memory with sliding window eviction."""

    def __init__(self, max_messages: int = 50, embedding_provider: Any | None = None) -> None:
        self.max_messages = max(2, max_messages)
        self.embedding_provider = embedding_provider
        self._messages: list[Message] = []
        self._embeddings: list[EmbeddingRecord] = []

    def add_message(self, message: Message) -> None:
        """Store a message and apply sliding window trimming if capacity is exceeded."""
        if message.role == Role.TOOL and message.content and len(message.content) > 1000:
            message = message.model_copy(update={"content": message.content[:1000] + "... [truncated to 1000 chars]"})
        self._messages.append(message)
        if len(self._messages) > self.max_messages:
            excess = len(self._messages) - self.max_messages
            self._messages = self._messages[excess:]
            logger.debug(f"Trimmed {excess} oldest message(s) from memory buffer.")

    def get_messages(self) -> list[Message]:
        """Return a copy of all current messages in buffer."""
        return list(self._messages)

    def clear(self) -> None:
        """Clear all messages from buffer."""
        self._messages.clear()
        logger.debug("Cleared memory buffer.")

    def get_context_window(
        self,
        max_messages: int = 50,
        max_turns: int | None = None,
        max_tokens: int = 3000,
    ) -> list[Message]:
        """Retrieve recent slice of messages up to max_messages with turn and token limits."""
        if max_messages <= 0:
            return []
        if max_turns is not None and max_turns > 0:
            effective_limit = min(max_messages, max_turns * 2)
        else:
            effective_limit = max_messages
        messages = list(self._messages[-effective_limit:])

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

    def search(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MemorySearchResult]:
        """Search in-memory messages by substring matching."""
        if not query or not query.strip():
            return []

        q = query.strip().lower()
        results: list[MemorySearchResult] = []
        for idx, msg in enumerate(self._messages):
            if q in msg.content.lower():
                if start_time and msg.timestamp < start_time:
                    continue
                if end_time and msg.timestamp > end_time:
                    continue
                results.append(
                    MemorySearchResult(
                        conversation_id="default",
                        conversation_title="Default Conversation",
                        message_id=str(idx),
                        role=msg.role,
                        content=msg.content,
                        timestamp=msg.timestamp,
                        score=1.0,
                    )
                )
        return results[:max(1, limit)]

    def add_embedding(self, record: EmbeddingRecord) -> None:
        """Store an embedding record in-memory."""
        if not hasattr(self, "_embeddings"):
            self._embeddings = []
        self._embeddings.append(record)

    def get_embeddings_for_conversation(self, conversation_id: str) -> list[EmbeddingRecord]:
        """Retrieve stored embedding records for conversation in-memory."""
        if not hasattr(self, "_embeddings"):
            self._embeddings = []
        return [e for e in self._embeddings if e.conversation_id == conversation_id]

    def search_semantic(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> list[SemanticSearchResult]:
        """Perform semantic cosine similarity search in-memory."""
        if not hasattr(self, "_embeddings") or not self._embeddings or not hasattr(self, "embedding_provider") or not self.embedding_provider:
            return []

        try:
            q_vec = self.embedding_provider.embed_text(query)
        except Exception:
            return []

        results = []
        for rec in self._embeddings:
            if conversation_id and rec.conversation_id != conversation_id:
                continue
            if len(rec.embedding) != len(q_vec):
                continue
            score = self._cosine_sim(q_vec, rec.embedding)
            if score >= threshold:
                results.append(
                    SemanticSearchResult(
                        record_id=rec.id,
                        conversation_id=rec.conversation_id,
                        message_id=rec.message_id,
                        source_text=rec.source_text,
                        score=round(score, 4),
                        created_at=rec.created_at,
                        metadata=rec.metadata,
                    )
                )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def search_hybrid(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Search in-memory with semantic fallback to keyword search."""
        if hasattr(self, "embedding_provider") and self.embedding_provider:
            sem_res = self.search_semantic(query, conversation_id=conversation_id, limit=limit, threshold=0.3)
            if sem_res:
                return [
                    MemorySearchResult(
                        conversation_id=sr.conversation_id,
                        conversation_title="Default Conversation",
                        message_id=sr.message_id or sr.record_id,
                        role=Role.ASSISTANT,
                        content=sr.source_text,
                        timestamp=sr.created_at,
                        score=sr.score,
                    )
                    for sr in sem_res
                ]
        return self.search(query=query, conversation_id=conversation_id, limit=limit)

    @staticmethod
    def _cosine_sim(u: list[float], v: list[float]) -> float:
        import math
        if not u or not v or len(u) != len(v):
            return 0.0
        dot = sum(a * b for a, b in zip(u, v))
        norm_u = math.sqrt(sum(a * a for a in u))
        norm_v = math.sqrt(sum(b * b for b in v))
        if norm_u == 0.0 or norm_v == 0.0:
            return 0.0
        return dot / (norm_u * norm_v)

    def __len__(self) -> int:
        return len(self._messages)

    def __bool__(self) -> bool:
        """Always truthy so `memory or fallback` idioms don't discard a valid empty memory."""
        return True
