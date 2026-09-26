"""Live, evidence-labelled status for FRIDAY Universe services."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.fleet_client import AgentStatus, FleetClient, fleet_client
from friday.ecosystem.registry import EcosystemRegistry
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.ecosystem_status")

_AGENT_NAMES = {
    "inference": "Inference",
    "memora": "Memora",
    "stratex": "Stratex",
    "intelx": "IntelX",
    "futuris": "Futuris",
    "cortex": "Cortex",
    "forge": "Forge",
    "sentinel": "Sentinel",
}


class EcosystemStatusSkill(BaseSkill):
    """Report live endpoint reachability without inventing task or business metrics."""

    name = "ecosystem_status"
    description = "Checks the configured FRIDAY Universe service health endpoints and labels what was verified."

    def __init__(
        self,
        registry: EcosystemRegistry | None = None,
        fleet: FleetClient | None = None,
    ) -> None:
        super().__init__()
        # A supplied registry is useful for offline diagnostics and tests. The
        # default command uses actual configured service probes.
        self.registry = registry
        self.fleet = fleet or fleet_client

    @staticmethod
    def _run_probe(coro) -> list[AgentStatus]:
        """Run an async fleet probe from both sync CLI and async server callers."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="friday-fleet-status") as pool:
            return pool.submit(asyncio.run, coro).result(timeout=20)

    def _registry_statuses(self) -> dict[str, tuple[str, str, str]]:
        result: dict[str, tuple[str, str, str]] = {}
        if self.registry is None:
            return result
        snapshot = self.registry.get_ecosystem_status()
        for key, row in snapshot.get("subsystems", {}).items():
            display = row.get("display_name") or _AGENT_NAMES.get(key, key.title())
            data = row.get("data") or {}
            status = str(data.get("status", row.get("status", "UNVERIFIED")))
            evidence = str(data.get("evidence", "Local registry value; no live service probe was run."))
            result[key] = (display, status, evidence)
        return result

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Probe all configured peers, or show an explicitly unverified local registry snapshot."""
        try:
            checked_at = datetime.now(timezone.utc).isoformat()
            if self.registry is not None:
                rows = self._registry_statuses()
                evidence_mode = "local registry snapshot; live reachability was not tested"
            else:
                statuses = self._run_probe(self.fleet.get_all_statuses(force_refresh=True))
                rows = {
                    item.id: (
                        item.name,
                        "HEALTH_ENDPOINT_OK" if item.status == "ONLINE" else item.status,
                        item.details,
                    )
                    for item in statuses
                }
                evidence_mode = "live HTTP health-endpoint probes"

            lines = [
                "# FRIDAY Universe Status",
                f"Checked at (UTC): {checked_at}",
                f"Evidence: {evidence_mode}",
                "",
                "| Agent | Status | Evidence |",
                "|---|---|---|",
            ]
            for key, name in _AGENT_NAMES.items():
                if key in rows:
                    display, status, evidence = rows[key]
                else:
                    display, status = name, "UNVERIFIED"
                    evidence = "No configured probe result is available."
                evidence = " ".join(str(evidence).split()).replace("|", "\\|")
                lines.append(f"| {display} | {status} | {evidence} |")

            lines.append("| FRIDAY (local) | RUNNING | This status request is executing in the local FRIDAY process. |")
            lines.extend([
                "",
                "A successful HTTP health check confirms only that endpoint responded. It does not verify background jobs, memory synchronization, agent-to-agent delivery, or completed tasks.",
            ])
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output="\n".join(lines),
                step_results=[{"action": "fleet_health_probe", "checked_at": checked_at, "probe_count": len(rows)}],
            )
        except Exception as exc:
            logger.error("Ecosystem status probe failed: %s", type(exc).__name__)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"FRIDAY could not complete the Universe status check: {type(exc).__name__}.",
                error=type(exc).__name__,
            )
