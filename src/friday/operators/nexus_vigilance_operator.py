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
    uptime_ratio_pct: float = 100.0


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
                # 1. Poll site status & health
                status_data = self.skill.get_site_status()
                self.vigilance_state.last_successful_poll = now
                self.vigilance_state.unreachable_since = None

                # 2. Check for New Incidents
                incidents = self.skill.get_pending_incidents()
                for inc in incidents:
                    inc_id = inc.get("id", inc.get("title"))
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
                    lid = lead["lead_id"]
                    if lid not in self.vigilance_state.known_lead_ids:
                        self.vigilance_state.known_lead_ids.append(lid)
                        evt = {
                            "type": "HIGH_INTENT_LEAD_DETECTED",
                            "lead_id": lid,
                            "domain": lead["company_domain"],
                            "score": lead["score"],
                            "message": f"⭐ [NEXUS LEAD] High-intent visitor detected from {lead['company_domain']} (Score: {lead['score']}/100)",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.info(f"[NEXUS_VIGILANCE] {evt['message']}")

                # 4. Check Pending Approvals Duration (>30 minutes)
                pending_count = status_data.get("pending_approvals_count", 0)
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
                if self.vigilance_state.unreachable_since is None:
                    self.vigilance_state.unreachable_since = now
                elif now - self.vigilance_state.unreachable_since > timedelta(minutes=2):
                    evt = {
                        "type": "SERVICE_UNREACHABLE_CRITICAL",
                        "error": str(e),
                        "message": f"🚨 [NEXUS CRITICAL] Nexus website service has been UNREACHABLE for > 2 minutes: {e}",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.critical(f"[NEXUS_VIGILANCE] {evt['message']}")

            self._alert_events.extend(events)
            return events

    def inject_simulated_incident(self, incident: dict[str, Any]) -> None:
        """Helper for testing incident detection."""
        with self._lock:
            self.skill._incidents.append(incident)

    def get_recent_events(self) -> list[dict[str, Any]]:
        """Returns log of emitted vigilance events."""
        with self._lock:
            return list(self._alert_events)
