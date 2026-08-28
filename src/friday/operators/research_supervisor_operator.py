# -*- coding: utf-8 -*-
"""Research Supervisor Operator for FRIDAY.

Supervises in-flight IntelX research tasks on a continuous 60-second polling cycle:
- Alerts on research task completion with findings breakdown and contradiction count
- Emits real-time info alert when a new factual contradiction is detected mid-run
- Dispatches voice alerts if a research task encounters execution failure
- Alerts critically if the IntelX research service becomes unreachable for >2 minutes
- Invariant: All data persisted or emitted carries TrustLevel.UNTRUSTED_EXTERNAL
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.skills.intelx_manager import IntelXManagerSkill

logger = get_logger("operators.research_supervisor")


@dataclass
class ResearchSupervisorState:
    """Internal state tracking active research runs, known completed runs, and contradictions."""
    last_poll_time: Optional[datetime] = None
    last_successful_poll: Optional[datetime] = None
    unreachable_since: Optional[datetime] = None
    known_completed_run_ids: List[str] = field(default_factory=list)
    known_contradiction_ids: List[str] = field(default_factory=list)
    known_failed_run_ids: List[str] = field(default_factory=list)


class ResearchSupervisorOperator(BaseOperator):
    """60-second continuous supervisor monitoring IntelX research tasks."""

    __test__ = False

    def __init__(
        self,
        skill: Optional[IntelXManagerSkill] = None,
        poll_interval_sec: float = 60.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="research_supervisor_poll_interval")
        super().__init__(
            name="research_supervisor_operator",
            description="Supervises IntelX research tasks, completed reports, mid-run contradictions, and health every 60s.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="intelx_research",
        )
        self.skill = skill or IntelXManagerSkill()
        self.poll_interval_sec = poll_interval_sec
        self.supervisor_state = ResearchSupervisorState()
        self._lock = threading.RLock()

    def run_cycle(self) -> List[Dict[str, Any]]:
        """Executes a single 60s supervisory evaluation across IntelX research runs."""
        now = datetime.now(timezone.utc)
        alerts: List[Dict[str, Any]] = []

        with self._lock:
            self.supervisor_state.last_poll_time = now

            # 1. Check IntelX Service Connectivity
            health = self.skill.get_intelx_health()
            if health.get("status") != "HEALTHY":
                if self.supervisor_state.unreachable_since is None:
                    self.supervisor_state.unreachable_since = now
                elif now - self.supervisor_state.unreachable_since > timedelta(minutes=2):
                    alerts.append({
                        "severity": "CRITICAL",
                        "title": "IntelX Research Engine Unreachable",
                        "voice_message": "Critical: IntelX Research engine has been unreachable for more than 2 minutes.",
                        "details": "Deep research query processing and synthesis pipelines are temporarily degraded.",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })
                return alerts

            self.supervisor_state.last_successful_poll = now
            self.supervisor_state.unreachable_since = None

            # 2. Check for Completed Research Runs
            for rid, run in self.skill._runs.items():
                if run.phase == "COMPLETED" and rid not in self.supervisor_state.known_completed_run_ids:
                    self.supervisor_state.known_completed_run_ids.append(rid)
                    verified_count = len(run.findings)
                    disputed_count = len(run.contradictions)
                    voice_msg = (
                        f"Your research on '{run.question}' is ready — "
                        f"{verified_count} verified findings, {disputed_count} disputed."
                    )
                    alerts.append({
                        "severity": "INFO",
                        "title": f"Research Completed: {run.question}",
                        "voice_message": voice_msg,
                        "details": f"Run ID: {rid} | Domain: {run.domain_hint} | Depth: {run.depth}",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })

                # 3. Check for Mid-Run Contradictions
                for c in run.contradictions:
                    cid = c.contradiction_id
                    if cid not in self.supervisor_state.known_contradiction_ids:
                        self.supervisor_state.known_contradiction_ids.append(cid)
                        alerts.append({
                            "severity": "INFO",
                            "title": f"Research Contradiction Detected: {c.topic}",
                            "voice_message": f"Contradiction found: two sources disagree on {c.topic}.",
                            "details": (
                                f"Side A ({c.source_a}): {c.claim_a}\n"
                                f"Side B ({c.source_b}): {c.claim_b}"
                            ),
                            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                        })

                # 4. Check for Failed Research Runs
                if run.phase == "FAILED" and rid not in self.supervisor_state.known_failed_run_ids:
                    self.supervisor_state.known_failed_run_ids.append(rid)
                    reason = run.failure_reason or "Unknown synthesis timeout"
                    alerts.append({
                        "severity": "WARNING",
                        "title": f"Research Task Failed: {run.question}",
                        "voice_message": f"IntelX research on '{run.question}' failed: {reason}.",
                        "details": f"Run ID: {rid} | Error: {reason}",
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    })

        return alerts
