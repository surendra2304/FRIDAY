# -*- coding: utf-8 -*-
"""Contextual Conversation Memory for FRIDAY Ecosystem.

Maintains a sliding 24-hour conversational context buffer for entity recall,
pronoun resolution ("How is it doing?"), and multi-turn dialogue continuity.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ecosystem.context_memory")


@dataclass
class ContextEntity:
    """Individual entity stored in conversational context memory."""
    entity_type: str  # project, strategy, task, asset
    value: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContextualConversationMemory:
    """Tracks conversational context with 24-hour TTL and pronoun resolution."""

    def __init__(self, ttl_hours: float = 24.0) -> None:
        self.ttl = timedelta(hours=ttl_hours)
        self._history: List[ContextEntity] = []
        self._lock = threading.RLock()

    def record_mention(
        self,
        entity_type: str,
        value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records a mentioned entity into context memory."""
        with self._lock:
            self._purge_expired()
            entity = ContextEntity(
                entity_type=entity_type,
                value=value,
                timestamp=datetime.now(timezone.utc),
                metadata=metadata or {},
            )
            self._history.append(entity)
            logger.debug(f"[CONTEXT_MEMORY] Recorded {entity_type}: {value}")

    def get_latest_mention(self, entity_type: Optional[str] = None) -> Optional[ContextEntity]:
        """Retrieves the most recent mentioned entity, optionally filtered by type."""
        with self._lock:
            self._purge_expired()
            if not self._history:
                return None
            if entity_type is None:
                return self._history[-1]
            for item in reversed(self._history):
                if item.entity_type == entity_type:
                    return item
            return None

    def resolve_pronoun_reference(self, query: str) -> Optional[Dict[str, Any]]:
        """Resolves ambiguous references ('it', 'that', 'the build', 'the strategy')."""
        clean = query.strip().lower()
        with self._lock:
            self._purge_expired()
            if not self._history:
                return None

            if any(k in clean for k in ["how is it doing", "what is its status", "how is that doing"]):
                latest = self._history[-1]
                return {
                    "resolved": True,
                    "entity_type": latest.entity_type,
                    "value": latest.value,
                    "metadata": latest.metadata,
                }

            if "build" in clean or "task" in clean or "project" in clean:
                task_item = self.get_latest_mention("task") or self.get_latest_mention("project")
                if task_item:
                    return {
                        "resolved": True,
                        "entity_type": task_item.entity_type,
                        "value": task_item.value,
                        "metadata": task_item.metadata,
                    }

            if "strategy" in clean or "trade" in clean:
                strat_item = self.get_latest_mention("strategy")
                if strat_item:
                    return {
                        "resolved": True,
                        "entity_type": strat_item.entity_type,
                        "value": strat_item.value,
                        "metadata": strat_item.metadata,
                    }

            return None

    def _purge_expired(self) -> None:
        """Removes context items older than the 24-hour TTL."""
        now = datetime.now(timezone.utc)
        cutoff = now - self.ttl
        self._history = [item for item in self._history if item.timestamp > cutoff]

    def clear(self) -> None:
        """Clears conversational memory."""
        with self._lock:
            self._history.clear()


# Default singleton context memory
context_memory = ContextualConversationMemory()
