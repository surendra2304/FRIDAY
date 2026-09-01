"""Sentinel Vigilance Operator for FRIDAY.

Supervises autonomous security posture and vulnerability intelligence on a 60-second polling cycle:
- Alerts on new CRITICAL findings (immediate voice alert: "Critical security finding on your website — {title}")
- Dispatches voice notifications on new HIGH severity findings
- Dispatches notifications on task completion with findings summary
- Issues reminder warnings when security approvals have been pending > 30 minutes
- Dispatches CRITICAL alert when Sentinel security service is unreachable > 2 minutes
- Invariant: All data persisted or emitted carries TrustLevel.UNTRUSTED_EXTERNAL.
- FRIDAY never executes security tools itself; all security actions go through Sentinel.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.skills.sentinel_manager import SentinelManagerSkill

logger = get_logger("operators.sentinel_vigilance")


@dataclass
class SentinelVigilanceState:
    """Internal state tracking known findings, task phases, pending approvals, and connectivity."""
    last_poll_time: datetime | None = None
    last_successful_poll: datetime | None = None
    unreachable_since: datetime | None = None
    known_finding_ids: list[str] = field(default_factory=list)
    known_completed_task_ids: list[str] = field(default_factory=list)
    pending_approvals_since: datetime | None = None
    last_known_critical_count: int = 0
    last_known_high_count: int = 0
    uptime_ratio_pct: float = 100.0


class SentinelVigilanceOperator(BaseOperator):
    """60-second continuous vigilance operator supervising Sentinel security assessments."""

    __test__ = False

    def __init__(
        self,
        skill: SentinelManagerSkill | None = None,
        poll_interval_sec: float = 60.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="sentinel_vigilance_poll_interval")
        super().__init__(
            name="sentinel_vigilance_operator",
            description="Supervises Sentinel security findings, critical vulnerabilities, and pending approvals every 60s.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="sentinel_security",
        )
        self.skill = skill or SentinelManagerSkill()
        self.poll_interval_sec = poll_interval_sec
        self.vigilance_state = SentinelVigilanceState()
        self._lock = threading.RLock()

    def run_cycle(self) -> list[dict[str, Any]]:
        """Executes a single 60s supervisory evaluation cycle across Sentinel security state."""
        now = datetime.now(timezone.utc)
        alerts: list[dict[str, Any]] = []

        with self._lock:
            self.vigilance_state.last_poll_time = now

            # 1. Check Sentinel Service Connectivity
            health = self.skill.get_sentinel_health()
            if health.get("status") != "HEALTHY":
                if self.vigilance_state.unreachable_since is None:
                    self.vigilance_state.unreachable_since = now
                elif now - self.vigilance_state.unreachable_since > timedelta(minutes=2):
                    alerts.append({
                        "severity": "CRITICAL",
                        "title": "Sentinel Security Engine Unreachable",
                        "voice_message": "Critical: Sentinel Security service has been unreachable for more than 2 minutes.",
                        "details": "Security vulnerability monitoring and perimeter tracking are temporarily degraded.",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })
                return alerts

            self.vigilance_state.last_successful_poll = now
            self.vigilance_state.unreachable_since = None

            # 2. Check for New CRITICAL and HIGH Findings
            findings = self.skill.get_findings()
            for f in findings:
                fid = f["finding_id"]
                sev = f["severity"].upper()
                if fid not in self.vigilance_state.known_finding_ids:
                    self.vigilance_state.known_finding_ids.append(fid)

                    if sev == "CRITICAL":
                        alerts.append({
                            "severity": "CRITICAL",
                            "title": f"Critical Security Finding: {f['title']}",
                            "voice_message": f"Critical security finding on your website — {f['title']} in {f['target_asset']}",
                            "details": (
                                f"Asset: {f['target_asset']} | Ref: {f.get('cve_or_cwe') or 'N/A'}\n"
                                f"Evidence: {f['evidence_reference']}\n"
                                f"Recommendation: {f['remediation_recommendation']}"
                            ),
                            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                        })
                    elif sev == "HIGH":
                        alerts.append({
                            "severity": "HIGH",
                            "title": f"High Security Finding: {f['title']}",
                            "voice_message": f"Security alert: New high-severity finding detected on {f['target_asset']} — {f['title']}",
                            "details": (
                                f"Asset: {f['target_asset']}\n"
                                f"Remediation: {f['remediation_recommendation']}"
                            ),
                            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                        })

            # 3. Check for Newly Completed Tasks
            for tid, t in self.skill._tasks.items():
                if t.phase == "COMPLETED" and tid not in self.vigilance_state.known_completed_task_ids:
                    self.vigilance_state.known_completed_task_ids.append(tid)
                    crit_count = sum(1 for x in t.findings if x.severity == "CRITICAL")
                    high_count = sum(1 for x in t.findings if x.severity == "HIGH")
                    alerts.append({
                        "severity": "INFO",
                        "title": f"Security Task Completed: {tid}",
                        "voice_message": f"Sentinel security assessment completed for {t.target}. Identified {crit_count} critical and {high_count} high vulnerabilities.",
                        "details": f"Target: {t.target} | Mode: {t.assessment_mode} | Total Findings: {t.findings_count}",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })

            # 4. Check for Pending High-Impact Approvals (>30 minutes)
            pending_actions = [a for a in self.skill._pending_actions.values() if a.status == "PENDING"]
            if pending_actions:
                if self.vigilance_state.pending_approvals_since is None:
                    self.vigilance_state.pending_approvals_since = now
                elif now - self.vigilance_state.pending_approvals_since > timedelta(minutes=30):
                    oldest = pending_actions[0]
                    alerts.append({
                        "severity": "WARNING",
                        "title": "Pending Security Action Awaiting Approval",
                        "voice_message": f"Reminder: High-impact security verification '{oldest.action_name}' has been pending approval for over 30 minutes.",
                        "details": f"Action ID: {oldest.action_id} | Target: {oldest.target} | Impact: {oldest.impact_level}",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })
            else:
                self.vigilance_state.pending_approvals_since = None

        return alerts
