# -*- coding: utf-8 -*-
"""Scheduled Intelligence Operator for FRIDAY Operating System.

Provides dynamic, context-aware scheduling beyond static cron:
1. Learned dynamic briefing times based on user morning voice routine (avg time ± 15 mins)
2. Context-aware scheduling aligned with market open sessions
3. Weather-aware schedule adjustments (delays/alerts during severe weather)
4. Calendar-aware skip conditions (defers spoken briefings when user is in a meeting)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger

logger = get_logger("operators.scheduled_intelligence")


@dataclass
class ScheduleEvaluationResult:
    """Outcome of intelligent schedule evaluation."""
    should_run: bool
    reason: str
    target_time_utc: str
    is_meeting_in_progress: bool = False
    is_severe_weather: bool = False
    market_status: str = "OPEN"


class ScheduledIntelligenceOperator(BaseOperator):
    """Dynamically schedules briefings based on user habits, market hours, and calendar state."""

    def __init__(
        self,
        default_morning_hour: int = 8,
        default_morning_minute: int = 30,
        poll_interval_sec: float = 60.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="sched_intel_poll")
        super().__init__(
            name="scheduled_intelligence_operator",
            description="Dynamically aligns briefings with user routine, market open, weather, and calendar.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="scheduled_intelligence",
        )
        self.default_hour = default_morning_hour
        self.default_minute = default_morning_minute
        self.voice_interaction_history: List[datetime] = []
        self._lock = threading.RLock()
        self._last_briefing_date: Optional[str] = None

    def record_voice_interaction(self, timestamp: Optional[datetime] = None) -> None:
        """Records user voice command timestamp to learn morning wake-up routine."""
        with self._lock:
            ts = timestamp or datetime.now(timezone.utc)
            self.voice_interaction_history.append(ts)

    def calculate_learned_briefing_time(self, target_date: Optional[datetime] = None) -> datetime:
        """Calculates optimal briefing time based on average morning voice interactions (±15 min)."""
        with self._lock:
            base_date = target_date or datetime.now(timezone.utc)
            morning_interactions = [
                t for t in self.voice_interaction_history
                if 5 <= t.hour <= 11
            ]

            if not morning_interactions:
                return base_date.replace(hour=self.default_hour, minute=self.default_minute, second=0, microsecond=0)

            # Compute average minute of day for morning interactions
            avg_minutes = sum(t.hour * 60 + t.minute for t in morning_interactions) / len(morning_interactions)
            learned_hour = int(avg_minutes // 60)
            learned_minute = int(avg_minutes % 60)

            return base_date.replace(hour=learned_hour, minute=learned_minute, second=0, microsecond=0)

    def evaluate_briefing_eligibility(
        self,
        current_time: Optional[datetime] = None,
        calendar_busy: bool = False,
        severe_weather_alert: bool = False,
        market_open: bool = True,
    ) -> ScheduleEvaluationResult:
        """Evaluates whether to execute morning briefing based on multi-context signals."""
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            target_time = self.calculate_learned_briefing_time(now)
            target_str = target_time.strftime("%H:%M UTC")

            # 1. Calendar skip condition: Do not interrupt during meetings
            if calendar_busy:
                return ScheduleEvaluationResult(
                    should_run=False,
                    reason="Skipped: User is currently in a scheduled calendar meeting. Deferring spoken briefing.",
                    target_time_utc=target_str,
                    is_meeting_in_progress=True,
                )

            # 2. Severe weather condition: Delay or adjust
            if severe_weather_alert:
                return ScheduleEvaluationResult(
                    should_run=False,
                    reason="Deferred: Severe weather alert in progress for user location.",
                    target_time_utc=target_str,
                    is_severe_weather=True,
                )

            # 3. Market open condition: Wait until session opens
            if not market_open:
                return ScheduleEvaluationResult(
                    should_run=False,
                    reason="Deferred: Target financial market is currently closed.",
                    target_time_utc=target_str,
                    market_status="CLOSED",
                )

            # 4. Check time window alignment (within 15 minutes of learned time)
            time_delta_mins = abs((now - target_time).total_seconds()) / 60.0
            if time_delta_mins <= 15.0:
                today_str = now.strftime("%Y-%m-%d")
                if self._last_briefing_date != today_str:
                    self._last_briefing_date = today_str
                    return ScheduleEvaluationResult(
                        should_run=True,
                        reason=f"Optimal briefing window reached ({target_str} ±15m).",
                        target_time_utc=target_str,
                    )

            return ScheduleEvaluationResult(
                should_run=False,
                reason=f"Outside optimal learned window ({target_str}).",
                target_time_utc=target_str,
            )

    def tick(self) -> List[Dict[str, Any]]:
        """Executes periodic schedule check."""
        with self._lock:
            res = self.evaluate_briefing_eligibility()
            if res.should_run:
                logger.info(f"[SCHEDULED_INTELLIGENCE] Triggering scheduled briefing ({res.reason})")
                return [{
                    "type": "DYNAMIC_BRIEFING_TRIGGERED",
                    "reason": res.reason,
                    "target_time": res.target_time_utc,
                }]
            return []
