"""Unified Ecosystem Intelligence Reporting Service for FRIDAY.

Aggregates operational telemetry and intelligence across all four managed subsystems:
- Algorithmic Trading Bot (Equity changes, positions, risk status, AI advisories)
- Nexus Website & Growth Engine (Visitors, high-intent leads, conversion rates, incidents)
- FORGE Software Engineering Engine (Completed tasks, active builds, test coverage, failures)
- AI-Universe Intelligence Core (Consultations served, provider health, cost, model confidence)

Generates Morning Briefings, Evening Wrap-Ups, and Weekly Strategic Reports with
weighted composite health scoring, voice-ready summaries, and 90-day retention persistence.
"""

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry

logger = get_logger("ecosystem.intelligence_service")


@dataclass
class EcosystemReport:
    """Structured container for ecosystem intelligence reports."""
    report_id: str
    report_type: str  # MORNING_BRIEFING, EVENING_WRAPUP, WEEKLY_REPORT
    composite_health_score: float | None
    spoken_summary: str
    markdown_report: str
    data_payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemIntelligenceService:
    """Consolidates intelligence across all 4 subsystems into structured reports."""

    def __init__(
        self,
        registry: EcosystemRegistry | None = None,
        reports_dir: str | None = None,
    ) -> None:
        self.registry = registry or ecosystem_registry
        self.reports_dir = Path(reports_dir or os.path.join("reports", "ecosystem"))
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def compute_composite_health_score(self, telemetry: dict[str, Any]) -> float | None:
        """Score only explicitly reported per-service health scores.

        Missing status or metrics are unknown, not an implicit healthy score.
        """
        names = ("trading_bot", "nexus", "forge", "ai_universe")
        scores: list[float] = []
        for name in names:
            entry = telemetry.get(name)
            if not isinstance(entry, dict) or str(entry.get("status", "")).upper() in {"", "UNVERIFIED", "UNKNOWN"}:
                return None
            try:
                value = float(entry["health_score"])
            except (KeyError, TypeError, ValueError):
                return None
            if not 0 <= value <= 100:
                return None
            scores.append(value)
        return round(sum(scores) / len(scores), 1)

    @staticmethod
    def _status_lines(telemetry: dict[str, Any]) -> list[str]:
        lines = []
        for name, data in telemetry.items():
            data = data if isinstance(data, dict) else {}
            status = str(data.get("status", "UNVERIFIED"))
            evidence = data.get("evidence")
            line = f"- **{name}:** `{status}`"
            if evidence:
                line += f" — {evidence}"
            metrics = {
                key: value for key, value in data.items()
                if key not in {"status", "evidence", "service", "checked_at"}
            }
            if metrics:
                line += f" | Observed metrics: `{json.dumps(metrics, sort_keys=True, default=str)}`"
            lines.append(line)
        return lines

    def generate_morning_briefing(self) -> EcosystemReport:
        """Generates the Morning Executive Briefing across all four subsystems."""
        with self._lock:
            status = self.registry.get_ecosystem_status()
            subs = status.get("subsystems", {})
            bot = subs.get("trading_bot", {}).get("data", {})
            forge = subs.get("forge", {}).get("data", {})
            ai = subs.get("ai_universe", {}).get("data", {})
            nexus = subs.get("nexus", {}).get("data", {})

            telemetry = {"trading_bot": bot, "forge": forge, "ai_universe": ai, "nexus": nexus}
            health_score = self.compute_composite_health_score(telemetry)
            report_id = f"morning_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            score_text = f"{health_score}/100" if health_score is not None else "UNVERIFIED"
            verified_count = sum(
                1 for data in telemetry.values()
                if isinstance(data, dict) and str(data.get("status", "")).upper() not in {"", "UNVERIFIED", "UNKNOWN"}
            )
            spoken = (
                f"Good morning. I checked {len(telemetry)} registered services; "
                f"{verified_count} returned a verified status. Composite health is {score_text}. "
                "No trading, traffic, lead, build, or provider totals are available unless a service supplied them."
            )
            md = (
                f"# FRIDAY Morning Ecosystem Report\n\n"
                f"**Report ID:** `{report_id}` | **Composite Health:** `{score_text}`\n\n"
                "## Observed service status\n"
                + "\n".join(self._status_lines(telemetry))
                + "\n\nMetrics absent from service responses are omitted; endpoint registration is not evidence of activity.\n"
            )

            report = EcosystemReport(
                report_id=report_id,
                report_type="MORNING_BRIEFING",
                composite_health_score=health_score,
                spoken_summary=spoken,
                markdown_report=md,
                data_payload=telemetry,
            )
            self.persist_report(report)
            return report

    def generate_evening_wrapup(self) -> EcosystemReport:
        """Generates Evening Wrap-Up with daily deltas and tomorrow's outlook."""
        with self._lock:
            status = self.registry.get_ecosystem_status()
            subs = status.get("subsystems", {})
            bot = subs.get("trading_bot", {}).get("data", {})
            forge = subs.get("forge", {}).get("data", {})
            nexus = subs.get("nexus", {}).get("data", {})
            ai = subs.get("ai_universe", {}).get("data", {})

            telemetry = {"trading_bot": bot, "forge": forge, "ai_universe": ai, "nexus": nexus}
            health_score = self.compute_composite_health_score(telemetry)
            report_id = f"evening_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            score_text = f"{health_score}/100" if health_score is not None else "UNVERIFIED"
            spoken = (
                f"Good evening. I checked {len(telemetry)} registered services. "
                "No verified daily activity or performance totals were returned."
            )
            md = (
                f"# FRIDAY Evening Ecosystem Report\n\n"
                f"**Report ID:** `{report_id}` | **Composite Health:** `{score_text}`\n\n"
                "## Observed service status\n"
                + "\n".join(self._status_lines(telemetry))
                + "\n\nNo event feed is connected, so daily totals and outlook claims are omitted.\n"
            )

            report = EcosystemReport(
                report_id=report_id,
                report_type="EVENING_WRAPUP",
                composite_health_score=health_score,
                spoken_summary=spoken,
                markdown_report=md,
                data_payload=telemetry,
            )
            self.persist_report(report)
            return report

    def generate_weekly_report(self) -> EcosystemReport:
        """Generates Sunday Evening Weekly Ecosystem Report with week-over-week trends."""
        with self._lock:
            status = self.registry.get_ecosystem_status()
            subs = status.get("subsystems", {})
            bot = subs.get("trading_bot", {}).get("data", {})
            forge = subs.get("forge", {}).get("data", {})
            nexus = subs.get("nexus", {}).get("data", {})
            ai = subs.get("ai_universe", {}).get("data", {})

            telemetry = {"trading_bot": bot, "forge": forge, "ai_universe": ai, "nexus": nexus}
            health_score = self.compute_composite_health_score(telemetry)
            report_id = f"weekly_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            score_text = f"{health_score}/100" if health_score is not None else "UNVERIFIED"
            spoken = (
                f"The weekly report is ready. Composite health is {score_text}. "
                "No verified weekly event or performance feed was returned."
            )
            md = (
                f"# FRIDAY Weekly Ecosystem Report\n\n"
                f"**Report ID:** `{report_id}` | **Composite Health:** `{score_text}`\n\n"
                "## Observed service status\n"
                + "\n".join(self._status_lines(telemetry))
                + "\n\nWeekly business metrics and recommendations require verified event and performance data.\n"
            )

            report = EcosystemReport(
                report_id=report_id,
                report_type="WEEKLY_REPORT",
                composite_health_score=health_score,
                spoken_summary=spoken,
                markdown_report=md,
                data_payload=telemetry,
            )
            self.persist_report(report)
            return report

    def persist_report(self, report: EcosystemReport) -> str:
        """Saves report to disk and prunes reports older than 90 days."""
        with self._lock:
            date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            file_base = f"{date_prefix}_{report.report_type.lower()}_{report.report_id}"
            json_path = self.reports_dir / f"{file_base}.json"
            md_path = self.reports_dir / f"{file_base}.md"

            # Write JSON payload
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "report_id": report.report_id,
                    "report_type": report.report_type,
                    "composite_health_score": report.composite_health_score,
                    "spoken_summary": report.spoken_summary,
                    "timestamp": report.timestamp,
                    "data_payload": report.data_payload,
                }, f, indent=2)

            # Write Markdown presentation
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(report.markdown_report)

            self._prune_90_day_retention()
            logger.info(f"[INTELLIGENCE_SERVICE] Persisted report {report.report_id} to {json_path}")
            return str(json_path)

    def _prune_90_day_retention(self) -> int:
        """Deletes reports older than 90 days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        pruned_count = 0

        for item in self.reports_dir.iterdir():
            if item.is_file() and (item.suffix in (".json", ".md")):
                mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    try:
                        item.unlink()
                        pruned_count += 1
                    except Exception as e:
                        logger.warning(f"[INTELLIGENCE_SERVICE] Error pruning {item}: {e}")

        if pruned_count > 0:
            logger.info(f"[INTELLIGENCE_SERVICE] Pruned {pruned_count} reports older than 90 days.")
        return pruned_count


# Default intelligence service instance
ecosystem_intelligence = EcosystemIntelligenceService()
