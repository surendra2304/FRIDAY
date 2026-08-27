# -*- coding: utf-8 -*-
"""Automated Follow-Up Workflow for FRIDAY Operating System.

Tracks FRIDAY's proactive recommendations and systematically follows up:
1. Recommendation outcome measurement: "I suggested pausing Supertrend 2 days ago — here's what happened since"
2. Gentle reminder for acknowledged but unacted alerts (> 24h)
3. Feedback calibration: outcome measurements automatically adjust recommendation confidence scores
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("workflows.followup")


@dataclass
class TrackedRecommendation:
    """A proactive suggestion provided to the user with lifecycle state."""
    rec_id: str
    subsystem: str
    proposed_action: str
    rationale: str
    baseline_metric: float  # e.g. -150.0 USDT or 2.1% conversion
    status: str = "PROPOSED"  # PROPOSED, ACKNOWLEDGED, ACCEPTED, REJECTED, EXPIRED
    confidence: float = 0.85
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_followup: Optional[datetime] = None


@dataclass
class FollowUpRecord:
    """Retrospective evaluation of a recommendation's impact."""
    rec_id: str
    followup_type: str  # OUTCOME_RETROSPECTIVE, UNACTED_REMINDER
    spoken_prompt: str
    delta_metric: float
    is_positive_outcome: bool
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AutomatedFollowUpWorkflow:
    """Manages recommendation tracking, 24h unacted reminders, and outcome retrospectives."""

    def __init__(self) -> None:
        self.recommendations: Dict[str, TrackedRecommendation] = {}
        self.followup_history: List[FollowUpRecord] = []
        self._lock = threading.RLock()

    def record_recommendation(
        self,
        rec_id: str,
        subsystem: str,
        proposed_action: str,
        rationale: str,
        baseline_metric: float = 0.0,
        confidence: float = 0.85,
    ) -> TrackedRecommendation:
        """Records a recommendation for subsequent outcome tracking."""
        with self._lock:
            rec = TrackedRecommendation(
                rec_id=rec_id,
                subsystem=subsystem,
                proposed_action=proposed_action,
                rationale=rationale,
                baseline_metric=baseline_metric,
                confidence=confidence,
            )
            self.recommendations[rec_id] = rec
            logger.info(f"[FOLLOWUP_WORKFLOW] Tracking recommendation {rec_id}: {proposed_action}")
            return rec

    def acknowledge_recommendation(self, rec_id: str) -> None:
        """Marks recommendation as acknowledged by user."""
        with self._lock:
            if rec_id in self.recommendations:
                self.recommendations[rec_id].status = "ACKNOWLEDGED"

    def evaluate_outcome(
        self,
        rec_id: str,
        current_metric: float,
        current_time: Optional[datetime] = None,
    ) -> Optional[FollowUpRecord]:
        """Generates retrospective outcome prompt (e.g. 'I suggested pausing Supertrend 2 days ago...')."""
        with self._lock:
            rec = self.recommendations.get(rec_id)
            if not rec:
                return None

            now = current_time or datetime.now(timezone.utc)
            days_elapsed = max(1, int((now - rec.created_at).total_seconds() / 86400.0))
            delta = current_metric - rec.baseline_metric
            is_positive = delta >= 0.0

            if "supertrend" in rec.proposed_action.lower() or "trading" in rec.subsystem:
                spoken = (
                    f"I suggested pausing Supertrend {days_elapsed} days ago — "
                    f"here's what happened since: performance delta is {delta:+.1f} USDT."
                )
            else:
                spoken = (
                    f"I suggested {rec.proposed_action} {days_elapsed} days ago. "
                    f"Outcome delta is {delta:+.1f}."
                )

            # Calibrate confidence
            if is_positive:
                rec.confidence = min(0.99, rec.confidence + 0.05)
            else:
                rec.confidence = max(0.50, rec.confidence - 0.05)

            rec.last_followup = now
            record = FollowUpRecord(
                rec_id=rec_id,
                followup_type="OUTCOME_RETROSPECTIVE",
                spoken_prompt=spoken,
                delta_metric=delta,
                is_positive_outcome=is_positive,
            )
            self.followup_history.append(record)
            return record

    def check_unacted_reminders(self, current_time: Optional[datetime] = None) -> List[FollowUpRecord]:
        """Generates gentle reminders for recommendations acknowledged but unacted for >24h."""
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            reminders: List[FollowUpRecord] = []

            for rec in self.recommendations.values():
                if rec.status == "ACKNOWLEDGED":
                    age = now - rec.created_at
                    if age >= timedelta(hours=24) and (not rec.last_followup or now - rec.last_followup >= timedelta(hours=24)):
                        spoken = (
                            f"Gentle reminder: you acknowledged my recommendation to {rec.proposed_action} "
                            f"yesterday. Would you like me to proceed with execution now?"
                        )
                        rec.last_followup = now
                        record = FollowUpRecord(
                            rec_id=rec.rec_id,
                            followup_type="UNACTED_REMINDER",
                            spoken_prompt=spoken,
                            delta_metric=0.0,
                            is_positive_outcome=True,
                        )
                        reminders.append(record)
                        self.followup_history.append(record)

            return reminders


# Default singleton instance
automated_followup = AutomatedFollowUpWorkflow()
