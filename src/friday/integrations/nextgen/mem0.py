"""Mem0 Memory Bridge for FRIDAY.

Adapts Mem0's semantic memory into FRIDAY's memory layer while preserving
FRIDAY's authoritative ownership of privacy, security, and retention.
"""

from __future__ import annotations

from typing import Any

from friday.memory.adapters.mem0_adapter import Mem0MemoryAdapter


class Mem0MemoryBridge:
    """Bridge for Mem0 memory provider."""

    def __init__(self, user_id: str = "friday_user", **kwargs: Any) -> None:
        self.user_id = user_id
        self.adapter = Mem0MemoryAdapter(user_id=user_id, mem0_config=kwargs)

    @property
    def available(self) -> bool:
        return self.adapter.is_available

    def add(self, content: str, role: str = "user") -> None:
        from friday.core.types import Message, Role

        r = Role.USER if role == "user" else Role.ASSISTANT
        self.adapter.add_message(Message(role=r, content=content))

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        results = self.adapter.search(query=query, limit=limit)
        return [{"content": r.content, "score": r.score} for r in results]
