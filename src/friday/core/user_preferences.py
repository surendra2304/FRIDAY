# -*- coding: utf-8 -*-
"""User Preferences & Adaptive Learning Subsystem for FRIDAY.

Manages personalized configuration across Voice, Reporting, and Trading domains.
Adapts preference weights over time based on interaction patterns.
Invariant: User preferences never override hardcoded safety gates or risk limits.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("core.user_preferences")


@dataclass
class VoicePreferences:
    speech_rate: float = 1.0
    volume: float = 0.8
    voice_type: str = "British_Professional"
    wake_word_sensitivity: float = 0.75


@dataclass
class ReportPreferences:
    detail_level: str = "normal"  # brief, normal, detailed
    briefing_frequency: str = "daily_morning_evening"
    preferred_metrics: List[str] = field(default_factory=lambda: ["equity_usdt", "daily_pnl", "test_coverage"])


@dataclass
class TradingPreferences:
    risk_tolerance: str = "MODERATE"  # CONSERVATIVE, MODERATE, AGGRESSIVE
    preferred_strategies: List[str] = field(default_factory=lambda: ["Supertrend", "VolumeBreakout"])
    max_daily_drawdown_limit_pct: float = 5.0  # Cannot override safety gate limit of 5.0%


class UserPreferenceManager:
    """Stores, loads, and adaptively updates personalized user preferences."""

    def __init__(self) -> None:
        self.voice = VoicePreferences()
        self.reports = ReportPreferences()
        self.trading = TradingPreferences()
        self._interaction_history: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def update_voice_preferences(self, **kwargs: Any) -> None:
        """Updates speech rate, volume, voice type, or wake word sensitivity."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self.voice, k):
                    setattr(self.voice, k, v)
            logger.info("[USER_PREFERENCES] Updated voice preferences.")

    def update_report_preferences(self, **kwargs: Any) -> None:
        """Updates detail level, briefing frequency, or metrics."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self.reports, k):
                    setattr(self.reports, k, v)
            logger.info("[USER_PREFERENCES] Updated report preferences.")

    def update_trading_preferences(self, **kwargs: Any) -> None:
        """Updates trading preferences with strict safety gate constraints."""
        with self._lock:
            for k, v in kwargs.items():
                if k == "max_daily_drawdown_limit_pct":
                    # Hardcoded Safety Gate: Cannot loosen beyond 5.0%
                    clamped = min(float(v), 5.0)
                    self.trading.max_daily_drawdown_limit_pct = clamped
                elif hasattr(self.trading, k):
                    setattr(self.trading, k, v)
            logger.info("[USER_PREFERENCES] Updated trading preferences with safety gate compliance.")

    def record_interaction_and_learn(self, query: str, context: Dict[str, Any]) -> None:
        """Learns usage patterns to tune reporting and recommendation weights."""
        with self._lock:
            self._interaction_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "context": context,
            })
            # Adaptive detail level tuning
            if len(self._interaction_history) >= 10:
                short_queries = sum(1 for item in self._interaction_history[-10:] if len(item["query"].split()) <= 3)
                if short_queries >= 7:
                    self.reports.detail_level = "brief"
                elif short_queries <= 2:
                    self.reports.detail_level = "detailed"


# Default preference singleton
user_preferences = UserPreferenceManager()
