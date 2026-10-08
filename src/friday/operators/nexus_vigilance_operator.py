"""Nexus Vigilance Operator for FRIDAY.

Continuously monitors Nexus Autonomous Website & Growth Engine on a 60-second cycle:
- Emits voice alerts for new website incidents with severity ratings
- Dispatches notifications when high-intent leads are identified
- Warns when approvals have been pending for > 30 minutes
- Triggers critical alerts when Nexus is unreachable for > 2 minutes
- Logs informational events when a website growth strategy is demoted
- Invariant: All data persisted to memory carries TrustLevel.UNTRUSTED_EXTERNAL.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.skills.nexus_operator import NexusOperatorSkill

logger = get_logger("operators.nexus_vigilance")


@dataclass
class NexusVigilanceState:
    """Internal state tracking known incidents, leads, and availability."""
    last_poll_time: datetime | None = None
    last_successful_poll: datetime | None = None
    unreachable_since: datetime | None = None
    known_incident_ids: list[str] = field(default_factory=list)
    known_lead_ids: list[str] = field(default_factory=list)
    pending_approvals_since: datetime | None = None
    #: None until at least one poll has been recorded; 100.0 here used to
    #: mean "no data" and "perfect uptime" at the same time.
    uptime_ratio_pct: float | None = None


class NexusVigilanceOperator(BaseOperator):
    """Persistent 60-second vigilance operator supervising Nexus website health and growth metrics."""

    def __init__(
        self,
        skill: NexusOperatorSkill | None = None,
        poll_interval_sec: float = 60.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="nexus_vigilance_poll_interval")
        super().__init__(
            name="nexus_vigilance_operator",
            description="Supervises Nexus autonomous website metrics and incidents every 60 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="nexus_vigilance",
        )
        self.skill = skill or NexusOperatorSkill()
        self.poll_interval_sec = poll_interval_sec
        self.vigilance_state = NexusVigilanceState()
        self._lock = threading.RLock()
        self._alert_events: list[dict[str, Any]] = []

    def tick(self) -> list[dict[str, Any]]:
        """Executes a 60-second polling cycle against Nexus APIs."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.vigilance_state.last_poll_time = now
            events: list[dict[str, Any]] = []

            try:
                # 1. Poll site status & health. A skill that reports
                # available=False did not answer: recording that as a
                # "successful poll" (which this line used to do unconditionally)
                # silenced exactly the outage the operator exists to notice.
                status_data = self.skill.get_site_status()
                if status_data.get("available") is False:
                    events.extend(self._record_unreachable(now, status_data.get("error") or "no response"))
                    self._alert_events.extend(events)
                    return events

                self.vigilance_state.last_successful_poll = now
                self.vigilance_state.unreachable_since = None

                # 2. Check for New Incidents
                incidents = self.skill.get_pending_incidents()
                for inc in incidents:
                    inc_id = inc.get("id") or inc.get("title")
                    if inc_id and inc_id not in self.vigilance_state.known_incident_ids:
                        self.vigilance_state.known_incident_ids.append(inc_id)
                        evt = {
                            "type": "NEW_INCIDENT",
                            "severity": inc.get("severity", "HIGH"),
                            "title": inc.get("title"),
                            "message": f"🚨 [NEXUS ALERT] New website incident [{inc.get('severity')}]: {inc.get('title')}",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.warning(f"[NEXUS_VIGILANCE] {evt['message']}")

                # 3. Check for High-Intent Leads
                leads = self.skill.get_high_intent_leads()
                for lead in leads:
                    # A lead payload that omits an id, domain or score used to
                    # raise KeyError here, which the outer handler reported as
                    # "SERVICE_UNREACHABLE_CRITICAL" - an outage invented from a
                    # malformed record.
                    lid = lead.get("lead_id")
                    if not lid or lid in self.vigilance_state.known_lead_ids:
                        continue
                    domain = lead.get("company_domain", "an unspecified domain")
                    score = lead.get("score")
                    self.vigilance_state.known_lead_ids.append(lid)
                    evt = {
                        "type": "HIGH_INTENT_LEAD_DETECTED",
                        "lead_id": lid,
                        "domain": domain,
                        "score": score,
                        "message": (
                            f"⭐ [NEXUS LEAD] High-intent visitor detected from {domain}"
                            + (f" (Score: {score}/100)" if isinstance(score, (int, float)) else " (score not reported)")
                        ),
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.info(f"[NEXUS_VIGILANCE] {evt['message']}")

                # 4. Check Pending Approvals Duration (>30 minutes)
                pending_count = status_data.get("pending_approvals_count")
                if not isinstance(pending_count, (int, float)):
                    pending_count = 0  # nothing was reported, so nothing is stale
                if pending_count > 0:
                    if self.vigilance_state.pending_approvals_since is None:
                        self.vigilance_state.pending_approvals_since = now
                    elif now - self.vigilance_state.pending_approvals_since > timedelta(minutes=30):
                        evt = {
                            "type": "PENDING_APPROVALS_STALE",
                            "pending_count": pending_count,
                            "message": f"⏳ [NEXUS REMINDER] {pending_count} website approvals have been pending for > 30 minutes.",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.warning(f"[NEXUS_VIGILANCE] {evt['message']}")
                else:
                    self.vigilance_state.pending_approvals_since = None

            except Exception as e:
                logger.error(f"[NEXUS_VIGILANCE] Polling error: {e}")
                events.extend(self._record_unreachable(now, str(e)))

            self._alert_events.extend(events)
            return events

    def _record_unreachable(self, now: datetime, reason: str) -> list[dict[str, Any]]:
        """Records a failed poll and escalates once the outage is long enough.

        Called both when Nexus refuses/answers with an error and when a poll
        raises, so a "no answer" from the skill cannot be mistaken for a
        successful but quiet website.
        """
        with self._lock:
            if self.vigilance_state.unreachable_since is None:
                self.vigilance_state.unreachable_since = now
                logger.warning(f"[NEXUS_VIGILANCE] Nexus did not answer: {reason}")
                return []
            if now - self.vigilance_state.unreachable_since <= timedelta(minutes=2):
                return []
            evt = {
                "type": "SERVICE_UNREACHABLE_CRITICAL",
                "error": reason,
                "message": f"🚨 [NEXUS CRITICAL] Nexus website service has been UNREACHABLE for > 2 minutes: {reason}",
                "timestamp": now.isoformat(),
                "trust_level": "UNTRUSTED_EXTERNAL",
            }
            logger.critical(f"[NEXUS_VIGILANCE] {evt['message']}")
            return [evt]

    def inject_simulated_incident(self, incident: dict[str, Any]) -> None:
        """Helper for testing incident detection."""
        with self._lock:
            self.skill._incidents.append(incident)

    def get_recent_events(self) -> list[dict[str, Any]]:
        """Returns log of emitted vigilance events."""
        with self._lock:
            return list(self._alert_events)
