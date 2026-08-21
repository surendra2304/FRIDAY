# -*- coding: utf-8 -*-
"""Episodic Environmental Memory for storing, indexing, and recalling structured observations safely.

Features:
- Stores derived structured observations (application context, UI state changes, verified facts) without raw screenshots.
- Indexes episodic facts with relevance, recency, importance, confidence, and task association.
- Low-value repetitive observation suppression (perceptual & semantic deduplication).
- Safe correction & forgetting mechanisms for environmental facts.
- Automatic fallback from semantic embeddings to SQLite FTS5 full-text search when embeddings fail/exhaust quota.
- Strict zero-persistence policy for credentials, passwords, tokens, raw screenshots, and private CoT.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.memory.base import BaseMemory
from friday.vision.screen_context import ScreenContext
from friday.vision.temporal import EnvironmentalChange, EnvironmentalChangeType

logger = get_logger("vision.episodic_memory")

# Redaction patterns for sensitive visual text
SENSITIVE_PATTERNS = [
    (re.compile(r"(TEST_GEMINI_API_KEY_PLACEHOLDER_17[a-zA-Z0-9_-]{33})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(Bearer\s+[a-zA-Z0-9_\-\.]{20,})", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s\n]+)['\"]?", re.IGNORECASE), r"\1: [REDACTED_PASSWORD]"),
    (re.compile(r"(api[_-]?key|secret|token)\s*[:=]\s*['\"]?([^'\"\s\n]+)['\"]?", re.IGNORECASE), r"\1: [REDACTED_SECRET]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[REDACTED_CARD_NUMBER]"),  # Credit card numbers
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),              # SSN
]


def redact_sensitive_visual_text(text: str) -> str:
    """Sanitize and redact sensitive credentials and private data from visual text."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    from friday.security.scrubber import redact_secrets
    return redact_secrets(sanitized)


class MemoryImportance(str, Enum):
    """Importance rating for episodic environmental memories."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class EpisodicEnvironmentalFact:
    """Structured, verifiable episodic fact derived from multimodal perception."""
    fact_id: str
    category: str
    fact_summary: str
    confidence: float
    importance: MemoryImportance
    source_application: Optional[str] = None
    window_title: Optional[str] = None
    task_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "category": self.category,
            "fact_summary": self.fact_summary,
            "confidence": self.confidence,
            "importance": self.importance.value,
            "source_application": self.source_application,
            "window_title": self.window_title,
            "task_id": self.task_id,
            "timestamp": self.timestamp.isoformat(),
            "is_active": self.is_active,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodicEnvironmentalFact":
        imp_str = str(data.get("importance", "MEDIUM")).upper()
        try:
            imp = MemoryImportance(imp_str)
        except ValueError:
            imp = MemoryImportance.MEDIUM

        ts_str = data.get("timestamp")
        ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)

        return cls(
            fact_id=str(data.get("fact_id", "")),
            category=str(data.get("category", "ENVIRONMENTAL_FACT")),
            fact_summary=str(data.get("fact_summary", "")),
            confidence=float(data.get("confidence", 1.0)),
            importance=imp,
            source_application=data.get("source_application"),
            window_title=data.get("window_title"),
            task_id=data.get("task_id"),
            timestamp=ts,
            is_active=bool(data.get("is_active", True)),
            superseded_by=data.get("superseded_by"),
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )


class EpisodicEnvironmentalMemoryManager:
    """Manages long-term structured visual and environmental episodic memory."""

    def __init__(self, memory: BaseMemory, max_facts_cache: int = 500) -> None:
        self.memory = memory
        self.max_facts_cache = max_facts_cache
        self._facts: Dict[str, EpisodicEnvironmentalFact] = {}
        self._hash_index: Dict[str, str] = {}  # sha256 -> fact_id
        self._fact_counter: int = 0

    def record_derived_fact(
        self,
        category: str,
        fact_summary: str,
        confidence: float = 0.9,
        importance: MemoryImportance = MemoryImportance.MEDIUM,
        source_application: Optional[str] = None,
        window_title: Optional[str] = None,
        task_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Optional[EpisodicEnvironmentalFact]:
        """Record a sanitized derived observation/fact to episodic memory."""
        if not fact_summary or not fact_summary.strip():
            return None

        # 1. Sanitize & Redact secrets
        clean_summary = redact_sensitive_visual_text(fact_summary.strip())
        content_key = f"{category.lower()}:{clean_summary.lower()}:{str(source_application).lower()}"
        content_hash = hashlib.sha256(content_key.encode("utf-8")).hexdigest()

        # 2. Duplicate suppression (if active identical fact exists, update timestamp/confidence)
        if content_hash in self._hash_index:
            existing_id = self._hash_index[content_hash]
            if existing_id in self._facts and self._facts[existing_id].is_active:
                existing = self._facts[existing_id]
                existing.timestamp = datetime.now(timezone.utc)
                existing.confidence = max(existing.confidence, confidence)
                return existing

        # 3. Create structured fact
        self._fact_counter += 1
        fact_id = f"fact_{self._fact_counter}_{int(datetime.now(timezone.utc).timestamp())}"

        fact = EpisodicEnvironmentalFact(
            fact_id=fact_id,
            category=category,
            fact_summary=clean_summary,
            confidence=confidence,
            importance=importance,
            source_application=source_application,
            window_title=window_title,
            task_id=task_id,
        )

        self._facts[fact_id] = fact
        self._hash_index[content_hash] = fact_id

        # 4. Mirror to underlying persistent conversation memory for FTS & semantic search
        msg = Message(
            role=Role.TOOL,
            content=f"[{category}] {clean_summary} (App: {source_application or 'N/A'})",
            name="episodic_environmental_fact",
        )
        try:
            self.memory.add_message(msg)
        except Exception as e:
            logger.debug(f"Memory add_message fallback: {e}")

        return fact

    def record_screen_observation(
        self,
        screen_context: ScreenContext,
        task_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Optional[EpisodicEnvironmentalFact]:
        """Convert a ScreenContext snapshot into a high-level episodic fact."""
        if screen_context.is_error or not screen_context.summary:
            return None

        imp = MemoryImportance.HIGH if screen_context.errors else MemoryImportance.MEDIUM
        return self.record_derived_fact(
            category="SCREEN_OBSERVATION",
            fact_summary=screen_context.summary,
            confidence=screen_context.overall_confidence,
            importance=imp,
            source_application=screen_context.active_application,
            window_title=screen_context.window_title,
            task_id=task_id,
            conversation_id=conversation_id,
        )

    def record_environmental_change(
        self,
        change: EnvironmentalChange,
        conversation_id: Optional[str] = None,
    ) -> Optional[EpisodicEnvironmentalFact]:
        """Record a meaningful environmental state transition to episodic memory."""
        if not change.is_meaningful or change.change_type == EnvironmentalChangeType.INSIGNIFICANT_NOISE:
            return None

        imp = MemoryImportance.HIGH if change.change_type == EnvironmentalChangeType.ERROR_APPEARED else MemoryImportance.MEDIUM
        return self.record_derived_fact(
            category=change.change_type.value,
            fact_summary=change.description,
            confidence=change.confidence,
            importance=imp,
            task_id=change.relevant_task_context,
            conversation_id=conversation_id,
        )

    def correct_fact(
        self,
        old_fact_id: str,
        new_fact_summary: str,
        reason: str = "Corrected observation",
    ) -> Optional[EpisodicEnvironmentalFact]:
        """Correct an obsolete or incorrect environmental fact."""
        if old_fact_id not in self._facts:
            return None

        old_fact = self._facts[old_fact_id]
        old_fact.is_active = False

        new_fact = self.record_derived_fact(
            category=old_fact.category,
            fact_summary=new_fact_summary,
            confidence=1.0,
            importance=old_fact.importance,
            source_application=old_fact.source_application,
            window_title=old_fact.window_title,
            task_id=old_fact.task_id,
        )

        if new_fact:
            old_fact.superseded_by = new_fact.fact_id
            new_fact.metadata["supersedes"] = old_fact_id
            new_fact.metadata["correction_reason"] = reason

        return new_fact

    def forget_fact(self, fact_id: str) -> bool:
        """Deactivate / forget an episodic environmental fact."""
        if fact_id in self._facts and self._facts[fact_id].is_active:
            self._facts[fact_id].is_active = False
            # Remove from hash index so it is completely forgotten
            for h, fid in list(self._hash_index.items()):
                if fid == fact_id:
                    del self._hash_index[h]
            return True
        return False

    def query_facts(
        self,
        query: str,
        category: Optional[str] = None,
        task_id: Optional[str] = None,
        min_confidence: float = 0.5,
        limit: int = 5,
        conversation_id: Optional[str] = None,
        include_fallback: bool = False,
    ) -> List[EpisodicEnvironmentalFact]:
        """Retrieve relevant active episodic facts matching query and filters."""
        # 1. Local in-memory active facts search
        clean_q = query.lower().strip()
        matched: List[EpisodicEnvironmentalFact] = []

        for fact in self._facts.values():
            if not fact.is_active or fact.confidence < min_confidence:
                continue
            if category and fact.category.upper() != category.upper():
                continue
            if task_id and fact.task_id != task_id:
                continue

            # Text relevance match
            if clean_q in fact.fact_summary.lower() or any(w in fact.fact_summary.lower() for w in clean_q.split() if len(w) > 3):
                matched.append(fact)

        # Sort by (importance, recency)
        importance_weights = {
            MemoryImportance.CRITICAL: 4,
            MemoryImportance.HIGH: 3,
            MemoryImportance.MEDIUM: 2,
            MemoryImportance.LOW: 1,
        }
        matched.sort(
            key=lambda f: (importance_weights.get(f.importance, 2), f.timestamp.timestamp()),
            reverse=True,
        )

        if matched or not include_fallback:
            return matched[:limit]

        # 2. Fallback to memory search (FTS5 / Semantic embeddings)
        try:
            target_conv = conversation_id or getattr(self.memory, "active_conversation_id", None)
            search_results = self.memory.search(query=query, conversation_id=target_conv, limit=limit)
            fallback_facts: List[EpisodicEnvironmentalFact] = []
            for r in search_results:
                if "episodic" in str(getattr(r, "role", "")).lower() or getattr(r, "role", None) == Role.TOOL:
                    fallback_facts.append(
                        EpisodicEnvironmentalFact(
                            fact_id=f"fts_{abs(hash(r.content)) % 10000}",
                            category="HISTORICAL_SEARCH_FALLBACK",
                            fact_summary=r.content,
                            confidence=0.8,
                            importance=MemoryImportance.MEDIUM,
                            timestamp=r.timestamp if hasattr(r, "timestamp") and r.timestamp else datetime.now(timezone.utc),
                        )
                    )
            return fallback_facts
        except Exception as e:
            logger.warning(f"Fallback episodic memory search failed: {e}")
            return []
