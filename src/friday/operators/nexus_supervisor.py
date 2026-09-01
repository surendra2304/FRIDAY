"""Nexus Supervisor Operator for FRIDAY.

Continuously monitors Nexus Autonomous Website & Growth Engine on a 30-second cycle:
- Alerts on new website incidents (voice alert with severity rating)
- Dispatches notifications when high-intent leads (>0.8 intent score) are detected with behavioral evidence
- Issues reminder warnings when approvals have been pending for > 30 minutes
- Detects conversion anomalies (conversion rate drop > 15%) and proactively offers diagnostic investigation
- Triggers CRITICAL alerts when Nexus website service is unreachable for > 2 minutes
- Invariant: All data persisted or emitted carries TrustLevel.UNTRUSTED_EXTERNAL.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.skills.nexus_manager import NexusManagerSkill

logger = get_logger("operators.nexus_supervisor")


@dataclass
class NexusSupervisorState:
    """Internal state tracking incidents, leads, approvals, and anomaly thresholds."""
    last_poll_time: datetime | None = None
    last_successful_poll: datetime | None = None
    unreachable_since: datetime | None = None
    known_incident_ids: list[str] = field(default_factory=list)
    known_lead_ids: list[str] = field(default_factory=list)
    pending_approvals_since: datetime | None = None
    baseline_conversion_rate: float = 3.82
    anomaly_alerted: bool = False
    uptime_ratio_pct: float = 100.0


class NexusSupervisorOperator(BaseOperator):
    """Persistent 30-second supervisor operator for Nexus website health and growth intelligence."""

    def __init__(
        self,
        skill: NexusManagerSkill | None = None,
        poll_interval_sec: float = 30.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="nexus_supervisor_poll_interval")
        super().__init__(
            name="nexus_supervisor_operator",
            description="Supervises Nexus autonomous website metrics, high-intent leads, incidents, and conversion anomalies every 30s.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="nexus_supervision",
        )
        self.skill = skill or NexusManagerSkill()
        self.poll_interval_sec = poll_interval_sec
        self.supervisor_state = NexusSupervisorState()
        self._lock = threading.RLock()
        self._alert_events: list[dict[str, Any]] = []

    def tick(self) -> list[dict[str, Any]]:
        """Executes a 30-second polling and supervision cycle against Nexus APIs."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.supervisor_state.last_poll_time = now
            events: list[dict[str, Any]] = []

            try:
                # 1. Poll Site Overview
                overview = self.skill.get_site_overview()
                self.supervisor_state.last_successful_poll = now
                self.supervisor_state.unreachable_since = None

                # 2. Alert 1: New Website Incidents (Voice Alert with Severity)
                incidents = self.skill.get_incidents()
                for inc in incidents:
                    inc_id = inc.get("id", inc.get("title"))
                    if inc_id and inc_id not in self.supervisor_state.known_incident_ids:
                        self.supervisor_state.known_incident_ids.append(inc_id)
                        severity = inc.get("severity", "HIGH")
                        evt = {
                            "type": "NEW_INCIDENT",
                            "severity": severity,
                            "title": inc.get("title"),
                            "voice_alert": f"🚨 Attention: New website incident [{severity}] detected: {inc.get('title')}.",
                            "message": f"🚨 [NEXUS SUPERVISOR] Incident [{severity}]: {inc.get('title')} — {inc.get('description', '')}",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.warning(f"[NEXUS_SUPERVISOR] {evt['message']}")

                # 3. Alert 2: High-Intent Leads (> 0.8 intent score) with Evidence
                visitors = self.skill.get_live_visitors()
                for v in visitors:
                    sid = v["session_id"]
                    if v.get("intent_score", 0.0) >= 0.8 and sid not in self.supervisor_state.known_lead_ids:
                        self.supervisor_state.known_lead_ids.append(sid)
                        comp = v.get("inferred_company") or "Enterprise Visitor"
                        actions_str = ", ".join(v.get("key_actions", [])) or "High engagement on pricing/docs"
                        evt = {
                            "type": "HIGH_INTENT_LEAD",
                            "session_id": sid,
                            "company": comp,
                            "intent_score": v["intent_score"],
                            "evidence": actions_str,
                            "message": f"⭐ [NEXUS HIGH INTENT] Visitor from {comp} reached {v['intent_score']:.2f} intent on `{v['current_page']}`. Evidence: {actions_str}",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.info(f"[NEXUS_SUPERVISOR] {evt['message']}")

                # 4. Alert 3: Pending Approvals > 30 Minutes
                pending_approvals = self.skill.get_pending_approvals()
                if pending_approvals:
                    if self.supervisor_state.pending_approvals_since is None:
                        self.supervisor_state.pending_approvals_since = now
                    elif now - self.supervisor_state.pending_approvals_since > timedelta(minutes=30):
                        count = len(pending_approvals)
                        evt = {
                            "type": "PENDING_APPROVAL_REMINDER",
                            "pending_count": count,
                            "actions": [a["action_id"] for a in pending_approvals],
                            "message": f"⏳ [NEXUS REMINDER] {count} website optimization action(s) awaiting your approval for > 30 minutes.",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.warning(f"[NEXUS_SUPERVISOR] {evt['message']}")
                else:
                    self.supervisor_state.pending_approvals_since = None

                # 5. Alert 4: Conversion Anomaly (> 15% drop below baseline)
                current_cr = overview.get("conversion_rate_today", self.supervisor_state.baseline_conversion_rate)
                if self.supervisor_state.baseline_conversion_rate > 0:
                    delta_pct = ((current_cr - self.supervisor_state.baseline_conversion_rate) / self.supervisor_state.baseline_conversion_rate) * 100
                    if delta_pct <= -15.0 and not self.supervisor_state.anomaly_alerted:
                        self.supervisor_state.anomaly_alerted = True
                        evt = {
                            "type": "CONVERSION_ANOMALY_DETECTED",
                            "current_rate": current_cr,
                            "baseline_rate": self.supervisor_state.baseline_conversion_rate,
                            "drop_pct": abs(delta_pct),
                            "voice_alert": f"⚠️ Website conversion rate dropped {abs(delta_pct):.1f}% below baseline to {current_cr:.2f}%. Would you like me to run an autonomous diagnosis?",
                            "message": f"⚠️ [NEXUS ANOMALY] Conversion rate dropped {abs(delta_pct):.1f}% (Current: {current_cr:.2f}%, Baseline: {self.supervisor_state.baseline_conversion_rate:.2f}%). Diagnosis recommended.",
                            "timestamp": now.isoformat(),
                            "trust_level": "UNTRUSTED_EXTERNAL",
                        }
                        events.append(evt)
                        logger.warning(f"[NEXUS_SUPERVISOR] {evt['message']}")
                    elif delta_pct > -10.0:
                        self.supervisor_state.anomaly_alerted = False

            except Exception as e:
                logger.error(f"[NEXUS_SUPERVISOR] Polling error: {e}")
                # 6. Alert 5: Nexus Unreachable > 2 Minutes (CRITICAL)
                if self.supervisor_state.unreachable_since is None:
                    self.supervisor_state.unreachable_since = now
                elif now - self.supervisor_state.unreachable_since > timedelta(minutes=2):
                    evt = {
                        "type": "NEXUS_UNREACHABLE_CRITICAL",
                        "error": str(e),
                        "voice_alert": "🚨 Critical alert: Nexus website engine has been unreachable for more than two minutes.",
                        "message": f"🚨 [NEXUS CRITICAL] Nexus website service has been UNREACHABLE for > 2 minutes: {e}",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.critical(f"[NEXUS_SUPERVISOR] {evt['message']}")

            self._alert_events.extend(events)
            return events

    def inject_incident(self, incident: dict[str, Any]) -> None:
        """Helper to inject simulated incidents for testing."""
        with self._lock:
            self.skill._active_incidents.append(incident)

    def set_conversion_rate(self, rate: float) -> None:
        """Helper to test conversion anomaly alerts."""
        with self._lock:
            self.skill._conversion_rate_today = rate

    def get_alert_history(self) -> list[dict[str, Any]]:
        """Returns complete list of emitted supervisor events."""
        with self._lock:
            return list(self._alert_events)
