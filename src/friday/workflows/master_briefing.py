"""Master Daily Briefing Workflow for FRIDAY.

Synthesizes high-level morning strategic briefings and evening performance wrap-ups
across all 8 subsystems in the unified ecosystem:
1. Quantitative Trading Overview
2. FORGE Software Engineering Status
3. Nexus Website & Growth Intelligence
4. Sentinel Autonomous Security & Vulnerability Posture
5. IntelX Autonomous Deep Research & Knowledge Posture
6. Futuris Probabilistic Forecasting & Risk Outlook
7. AI-Universe Intelligence & Strategic Advisory
8. FRIDAY Multimodal OS Health & Memory Consolidation
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from friday.core.logging import get_logger
from friday.core.types import TrustLevel
from friday.ecosystem.registry import EcosystemRegistry
from friday.observability.proactive_engine import SystemSnapshot, capture_snapshot

logger = get_logger("workflows.master_briefing")


@dataclass
class MasterBriefingSnapshot:
    """Snapshot of a compiled multi-subsystem daily briefing."""
    briefing_id: str
    briefing_type: str  # MORNING, EVENING
    spoken_summary: str
    markdown_report: str
    subsystems_included: list[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trust_level: str = TrustLevel.UNTRUSTED_EXTERNAL.value


class MasterDailyBriefingWorkflow:
    """Orchestrates morning strategic debriefs and evening performance wrap-ups."""

    def __init__(self, registry: EcosystemRegistry | None = None) -> None:
        self.registry = registry or EcosystemRegistry()
        self._history: list[MasterBriefingSnapshot] = []
        self._lock = threading.RLock()

    def _collect_status(self) -> tuple[dict[str, object], SystemSnapshot]:
        """Collect local OS measurements and configured subsystem callback results."""
        return self.registry.get_ecosystem_status(), capture_snapshot()

    @staticmethod
    def _local_status(snapshot: SystemSnapshot) -> str:
        if snapshot.measurement_error:
            return f"Measurements unavailable: {snapshot.measurement_error}."
        cpu = f"{snapshot.cpu_percent:.1f}%" if snapshot.cpu_percent is not None else "unavailable"
        memory = f"{snapshot.ram_percent:.1f}%" if snapshot.ram_percent is not None else "unavailable"
        disk = f"{snapshot.disk_percent:.1f}%" if snapshot.disk_percent is not None else "unavailable"
        battery = (
            f"{snapshot.battery_percent:.0f}%"
            if snapshot.battery_percent is not None
            else "unavailable"
        )
        return (
            f"CPU {cpu}, memory {memory}, disk {disk}, battery {battery}."
        )

    @staticmethod
    def _service_status_lines(subsystems: dict[str, object]) -> list[str]:
        lines = []
        for info in subsystems.values():
            if not isinstance(info, dict):
                continue
            name = str(info.get("display_name", info.get("name", "Unknown service")))
            data = info.get("data", {})
            data = data if isinstance(data, dict) else {}
            status = str(info.get("status", data.get("status", "UNVERIFIED")))
            evidence = data.get("evidence")
            line = f"- **{name}:** `{status}`"
            if evidence:
                line += f" — {evidence}"
            lines.append(line)
        return lines

    def generate_morning_briefing(self) -> MasterBriefingSnapshot:
        """Compiles morning strategic briefing across all 8 subsystems."""
        with self._lock:
            bid = f"mb-morn-{len(self._history)+1:03d}"
            try:
                status, local = self._collect_status()
                subs = status.get("subsystems", {})
                service_lines = self._service_status_lines(subs)
                unverified = sum(
                    1 for info in subs.values()
                    if isinstance(info, dict) and str(info.get("status", "UNVERIFIED")).upper() == "UNVERIFIED"
                )
                spoken = (
                    f"Good morning. Your local computer check shows {self._local_status(local)} "
                    f"I checked {len(subs)} registered Friday Universe services; "
                    f"{unverified} are unverified because no live probe is configured. "
                    "I have no verified trading, lead, research, or forecast figures to report."
                )
                lines = [
                    f"# 🌅 FRIDAY Morning Briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                    "",
                    "## Local computer (measured now)",
                    f"- {self._local_status(local)}",
                    "",
                    "## Friday Universe service status",
                    *service_lines,
                    "",
                    "",
                    "No agent metrics or completed work are inferred from health status. Service state is shown only as returned by the configured registry callback.",
                ]

                snapshot = MasterBriefingSnapshot(
                    briefing_id=bid,
                    briefing_type="MORNING",
                    spoken_summary=spoken,
                    markdown_report="\n".join(lines),
                    subsystems_included=list(subs.keys()),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL.value,
                )
                self._history.append(snapshot)
                return snapshot

            except Exception as e:
                logger.error(f"[MASTER_BRIEFING] Morning briefing compilation failed: {e}")
                raise

    def generate_evening_briefing(self) -> MasterBriefingSnapshot:
        """Compiles 8-system evening performance wrap-up briefing."""
        import uuid
        bid = f"mb-eve-{uuid.uuid4().hex[:6]}"
        try:
            status, local = self._collect_status()
            subs = status.get("subsystems", {})
            service_lines = self._service_status_lines(subs)
            spoken = (
                f"Good evening. Your local computer check shows {self._local_status(local)} "
                f"I checked {len(subs)} registered Friday Universe services. "
                "Their returned status is listed in the report; I have no verified daily activity or performance totals to report."
            )
            lines = [
                f"# 🌃 FRIDAY Evening Briefing — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                "",
                "## Local computer (measured now)",
                f"- {self._local_status(local)}",
                "",
                "## Friday Universe service status",
                *service_lines,
                "",
                "Daily accomplishments and performance totals are omitted because no verified event feed is connected.",
            ]

            snapshot = MasterBriefingSnapshot(
                briefing_id=bid,
                briefing_type="EVENING",
                spoken_summary=spoken,
                markdown_report="\n".join(lines),
                subsystems_included=list(subs.keys()),
                created_at=datetime.now(timezone.utc).isoformat(),
                trust_level=TrustLevel.UNTRUSTED_EXTERNAL.value,
            )
            self._history.append(snapshot)
            logger.info(f"[MASTER_BRIEFING] Generated Evening Performance Wrap-Up '{bid}'")
            return snapshot

        except Exception as e:
            logger.error(f"[MASTER_BRIEFING] Evening briefing compilation failed: {e}")
            raise

    def generate_evening_wrapup(self) -> MasterBriefingSnapshot:
        """Alias for generate_evening_briefing."""
        return self.generate_evening_briefing()


MasterBriefingWorkflow = MasterDailyBriefingWorkflow
