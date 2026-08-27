# -*- coding: utf-8 -*-
"""Memory Consolidation Engine for FRIDAY Operating System.

Implements biological-inspired memory consolidation:
1. Nightly 03:00 consolidation job
2. Episodic-to-semantic compression (specific events -> generalized knowledge)
3. Multi-factor memory importance scoring (access frequency + recency + emotional/stress weight)
4. 30-day half-life decay for unaccessed memories
5. Archival of raw historical events into cold storage preserving active memory compactness
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("memory.consolidation")


@dataclass
class EpisodicEvent:
    """A granular, timestamped interaction or operational event."""
    event_id: str
    subsystem: str  # trading_bot, nexus, forge, ai_universe, ecosystem
    action: str
    details: Dict[str, Any]
    emotional_weight: float = 1.0  # 1.0 = normal, 2.0 = panic/stress, 1.5 = high priority
    access_count: int = 1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SemanticMemory:
    """A synthesized, high-level piece of generalized knowledge."""
    memory_id: str
    concept: str
    summary: str
    importance_score: float
    confidence: float
    derived_from_count: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryConsolidationEngine:
    """Orchestrates episodic-to-semantic compression, decay, and cold storage archiving."""

    def __init__(self, cold_storage_dir: Optional[str] = None) -> None:
        self.cold_storage_dir = Path(cold_storage_dir or os.path.join("memory", "cold_storage"))
        self.cold_storage_dir.mkdir(parents=True, exist_ok=True)
        self.episodic_memory: List[EpisodicEvent] = []
        self.semantic_memory: Dict[str, SemanticMemory] = {}
        self._lock = threading.RLock()
        self._last_consolidation_time: Optional[datetime] = None

    def record_event(
        self,
        subsystem: str,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        emotional_weight: float = 1.0,
    ) -> EpisodicEvent:
        """Records an episodic event into active short-term memory."""
        with self._lock:
            now = datetime.now(timezone.utc)
            event_id = f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{len(self.episodic_memory):04d}"
            event = EpisodicEvent(
                event_id=event_id,
                subsystem=subsystem,
                action=action,
                details=details or {},
                emotional_weight=emotional_weight,
                timestamp=now,
                last_accessed=now,
            )
            self.episodic_memory.append(event)
            return event

    def compute_importance_score(
        self,
        access_count: int,
        recency_hours: float,
        emotional_weight: float = 1.0,
    ) -> float:
        """Calculates multi-factor memory importance score (0.0 - 100.0)."""
        # Recency decay factor (higher score for recent events)
        recency_factor = max(0.1, 1.0 - (recency_hours / (24.0 * 30.0)))
        # Frequency bonus (logarithmic scaling)
        frequency_factor = min(3.0, 1.0 + (access_count * 0.1))
        # Emotional / stress weight multiplier
        stress_multiplier = max(1.0, emotional_weight)

        score = (50.0 * recency_factor) * frequency_factor * stress_multiplier
        return round(min(100.0, max(0.0, score)), 2)

    def apply_memory_decay(self, decay_threshold_days: float = 30.0) -> int:
        """Halves importance score of semantic memories unaccessed for > 30 days."""
        with self._lock:
            now = datetime.now(timezone.utc)
            decayed_count = 0
            for mem in self.semantic_memory.values():
                age_days = (now - mem.last_accessed).total_seconds() / 86400.0
                if age_days > decay_threshold_days:
                    mem.importance_score = round(mem.importance_score * 0.5, 2)
                    decayed_count += 1
            if decayed_count > 0:
                logger.info(f"[CONSOLIDATION] Applied 30-day half-life decay to {decayed_count} stale memories.")
            return decayed_count

    def compress_episodic_to_semantic(self) -> List[SemanticMemory]:
        """Compresses granular episodic events into generalized semantic concepts."""
        with self._lock:
            if not self.episodic_memory:
                return list(self.semantic_memory.values())

            # Group events by subsystem & intent pattern
            grouped: Dict[Tuple[str, str], List[EpisodicEvent]] = {}
            for ev in self.episodic_memory:
                pair = (ev.subsystem, ev.action)
                grouped.setdefault(pair, []).append(ev)

            new_semantics: List[SemanticMemory] = []
            now = datetime.now(timezone.utc)

            for (subsystem, action), events in grouped.items():
                count = len(events)
                avg_stress = sum(e.emotional_weight for e in events) / count
                importance = self.compute_importance_score(access_count=count, recency_hours=1.0, emotional_weight=avg_stress)

                if subsystem == "trading_bot" and count >= 5:
                    concept = "active_trading_monitoring"
                    summary = f"User is actively monitoring quantitative trading operations (checked {count} times this cycle)."
                elif subsystem == "nexus" and count >= 3:
                    concept = "growth_lead_tracking"
                    summary = f"User is tracking website growth and enterprise lead conversions ({count} queries)."
                elif subsystem == "forge":
                    concept = "software_engineering_pipeline"
                    summary = f"User frequently commands FORGE for autonomous builds ({count} tasks)."
                else:
                    concept = f"{subsystem}_{action}_pattern"
                    summary = f"Regular interaction with {subsystem} for {action} ({count} occurrences)."

                mem_id = f"sem_{concept}"
                semantic = SemanticMemory(
                    memory_id=mem_id,
                    concept=concept,
                    summary=summary,
                    importance_score=importance,
                    confidence=0.92,
                    derived_from_count=count,
                    last_accessed=now,
                )
                self.semantic_memory[mem_id] = semantic
                new_semantics.append(semantic)

            # Archive compressed episodic events to cold storage and clear active queue
            self._archive_to_cold_storage(self.episodic_memory)
            self.episodic_memory.clear()

            logger.info(f"[CONSOLIDATION] Synthesized {len(new_semantics)} semantic memories.")
            return new_semantics

    def _archive_to_cold_storage(self, events: List[EpisodicEvent]) -> str:
        """Persists compressed episodic events to cold storage files."""
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        cold_file = self.cold_storage_dir / f"episodic_{month_key}.json"

        existing = []
        if cold_file.exists():
            try:
                with open(cold_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        serialized = [
            {
                "event_id": e.event_id,
                "subsystem": e.subsystem,
                "action": e.action,
                "details": e.details,
                "emotional_weight": e.emotional_weight,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in events
        ]
        existing.extend(serialized)

        with open(cold_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        return str(cold_file)

    def run_nightly_consolidation(self) -> Dict[str, Any]:
        """Executes full nightly memory consolidation routine (scheduled at 03:00)."""
        with self._lock:
            now = datetime.now(timezone.utc)
            decayed = self.apply_memory_decay(decay_threshold_days=30.0)
            semantics = self.compress_episodic_to_semantic()
            self._last_consolidation_time = now

            return {
                "status": "CONSOLIDATION_COMPLETE",
                "timestamp": now.isoformat(),
                "decayed_memories_count": decayed,
                "active_semantic_memories_count": len(self.semantic_memory),
                "cold_storage_preserved": True,
            }


# Default singleton instance
memory_consolidation = MemoryConsolidationEngine()
