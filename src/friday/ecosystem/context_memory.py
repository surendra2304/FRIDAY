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


@dataclass
class ContextQueryRecord:
    """Record of a recent query for follow-up resolution."""
    query: str
    target_subsystem: Optional[str]
    time_window: str = "today"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ContextualConversationMemory:
    """Tracks conversational context with 24-hour TTL, pronoun resolution, and temporal follow-ups."""

    def __init__(self, ttl_hours: float = 24.0) -> None:
        self.ttl = timedelta(hours=ttl_hours)
        self._history: List[ContextEntity] = []
        self._query_history: List[ContextQueryRecord] = []
        self._lock = threading.RLock()

    def record_query(
        self,
        query: str,
        target_subsystem: Optional[str] = None,
        time_window: str = "today",
    ) -> None:
        """Records a user query for conversational follow-ups."""
        with self._lock:
            self._purge_expired()
            self._query_history.append(
                ContextQueryRecord(
                    query=query,
                    target_subsystem=target_subsystem,
                    time_window=time_window,
                    timestamp=datetime.now(timezone.utc),
                )
            )

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
        """Resolves ambiguous references ('it', 'that', 'the build', 'the strategy', 'the website')."""
        clean = query.strip().lower()
        with self._lock:
            self._purge_expired()
            if not self._history:
                return None

            if any(k in clean for k in ["how is it doing", "what is its status", "how is that doing", "how is it"]):
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

            if "strategy" in clean or "trade" in clean or "positions" in clean:
                strat_item = self.get_latest_mention("strategy") or self.get_latest_mention("trading_bot")
                if strat_item:
                    return {
                        "resolved": True,
                        "entity_type": strat_item.entity_type,
                        "value": strat_item.value,
                        "metadata": strat_item.metadata,
                    }

            if "website" in clean or "site" in clean or "nexus" in clean:
                web_item = self.get_latest_mention("nexus") or self.get_latest_mention("website")
                if web_item:
                    return {
                        "resolved": True,
                        "entity_type": web_item.entity_type,
                        "value": web_item.value,
                        "metadata": web_item.metadata,
                    }

            return None

    def resolve_temporal_follow_up(self, query: str) -> Optional[Dict[str, Any]]:
        """Resolves temporal follow-up queries (e.g. 'What about yesterday?', 'How about this week?')."""
        clean = query.strip().lower()
        with self._lock:
            self._purge_expired()
            if not self._query_history:
                return None

            last_query = self._query_history[-1]
            time_match = None
            if "yesterday" in clean:
                time_match = "yesterday"
            elif "this week" in clean:
                time_match = "this week"
            elif "last month" in clean:
                time_match = "last month"
            elif "overnight" in clean:
                time_match = "overnight"
            elif "today" in clean:
                time_match = "today"

            if time_match and (clean.startswith("what about") or clean.startswith("how about") or clean.startswith("and")):
                return {
                    "resolved": True,
                    "original_query": last_query.query,
                    "target_subsystem": last_query.target_subsystem,
                    "new_time_window": time_match,
                    "message": f"Resolved follow-up for {last_query.target_subsystem or 'subsystem'} focusing on {time_match}.",
                }

            return None

    def _purge_expired(self) -> None:
        """Removes context items older than the 24-hour TTL."""
        now = datetime.now(timezone.utc)
        cutoff = now - self.ttl
        self._history = [item for item in self._history if item.timestamp > cutoff]
        self._query_history = [q for q in self._query_history if q.timestamp > cutoff]

    def clear(self) -> None:
        """Clears conversational memory."""
        with self._lock:
            self._history.clear()
            self._query_history.clear()


# Default singleton context memory
context_memory = ContextualConversationMemory()
