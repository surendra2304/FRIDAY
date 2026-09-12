"""Suggestion Engine — Proactive, Rate-Limited Contextual Assistance.

Adapted from Jarvis awareness/suggestion-engine.ts.
Evaluates workspace events, struggle detections, and repetitive actions to generate
actionable, non-intrusive suggestions with strict per-type rate-limiting and deduplication.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from friday.awareness.struggle_detector import StruggleAnalysis
from friday.core.logging import get_logger

logger = get_logger("awareness.suggestion_engine")


class SuggestionType(str, Enum):
    ERROR = "error"
    STRUGGLE = "struggle"
    STUCK = "stuck"
    AUTOMATION = "automation"
    BREAK = "break"
    GENERAL = "general"


@dataclass
class Suggestion:
    type: SuggestionType
    title: str
    description: str
    suggested_action: str
    confidence: float
    timestamp: float


# Per-type cooldowns to avoid annoying the user
TYPE_RATE_LIMITS: dict[SuggestionType, float] = {
    SuggestionType.ERROR: 15.0,        # 15s - errors are urgent
    SuggestionType.STRUGGLE: 90.0,     # 90s - behavioral struggle
    SuggestionType.STUCK: 60.0,        # 60s - unchanging screen/app
    SuggestionType.AUTOMATION: 120.0,  # 2min - proactive workflow suggestions
    SuggestionType.BREAK: 600.0,       # 10min - break reminders
    SuggestionType.GENERAL: 60.0,
}


class SuggestionEngine:
    """Evaluates context and events to produce rate-limited suggestions."""

    def __init__(self, default_rate_limit_s: float = 60.0) -> None:
        self.default_rate_limit_s = default_rate_limit_s
        self.last_suggestion_by_type: dict[SuggestionType, float] = {}
        self.recent_hashes: set[str] = set()
        self.hash_queue: list[str] = []

    def _hash_suggestion(self, title: str, description: str) -> str:
        content = f"{title}:{description}".lower().strip()
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

    def _is_deduped(self, h: str) -> bool:
        return h in self.recent_hashes

    def _record_hash(self, h: str) -> None:
        self.recent_hashes.add(h)
        self.hash_queue.append(h)
        if len(self.hash_queue) > 50:
            old = self.hash_queue.pop(0)
            self.recent_hashes.discard(old)

    def _can_fire(self, stype: SuggestionType, now: float) -> bool:
        if stype not in self.last_suggestion_by_type:
            return True
        last = self.last_suggestion_by_type[stype]
        limit = TYPE_RATE_LIMITS.get(stype, self.default_rate_limit_s)
        return (now - last) >= limit

    def evaluate_struggle(
        self,
        struggle: StruggleAnalysis,
        timestamp: Optional[float] = None,
    ) -> Optional[Suggestion]:
        """Convert a confirmed struggle analysis into a proactive assistance suggestion."""
        now = timestamp if timestamp is not None else time.monotonic()
        if not struggle or not struggle.is_struggling:
            return None

        stype = SuggestionType.ERROR if struggle.error_summary and "Error" in struggle.error_summary else SuggestionType.STRUGGLE
        if not self._can_fire(stype, now):
            return None

        if stype == SuggestionType.ERROR:
            title = f"Fix {struggle.app_name} Error"
            desc = f"Detected error in {struggle.app_name}: {struggle.error_summary}."
            action = f"Inspect terminal output and debug {struggle.error_summary}"
        else:
            title = f"Workspace Assistance for {struggle.app_name}"
            desc = f"Detected persistent trial-and-error editing in {struggle.app_name}."
            action = f"Offer assistance with current task in {struggle.app_name}"

        h = self._hash_suggestion(title, desc)
        if self._is_deduped(h):
            return None

        self._record_hash(h)
        self.last_suggestion_by_type[stype] = now

        suggestion = Suggestion(
            type=stype,
            title=title,
            description=desc,
            suggested_action=action,
            confidence=round(struggle.composite_score, 2),
            timestamp=now,
        )
        logger.info("Generated proactive suggestion: %s - %s", title, desc)
        return suggestion

    def evaluate_break(self, continuous_active_minutes: float, timestamp: Optional[float] = None) -> Optional[Suggestion]:
        """Suggest taking a brief break after extended continuous focus (>90 minutes)."""
        now = timestamp if timestamp is not None else time.monotonic()
        if continuous_active_minutes < 90.0:
            return None

        if not self._can_fire(SuggestionType.BREAK, now):
            return None

        title = "Take a Short Break"
        desc = f"You've been working continuously for {int(continuous_active_minutes)} minutes. A 5-minute break will boost focus."
        action = "Rest eyes, stretch, or hydrate."

        h = self._hash_suggestion(title, desc)
        if self._is_deduped(h):
            return None

        self._record_hash(h)
        self.last_suggestion_by_type[SuggestionType.BREAK] = now

        return Suggestion(
            type=SuggestionType.BREAK,
            title=title,
            description=desc,
            suggested_action=action,
            confidence=0.85,
            timestamp=now,
        )


# Global instance
suggestion_engine = SuggestionEngine()
