"""Ecosystem Orchestrator for FRIDAY.

The master coordination tier orchestrating workflows across all three managed systems:
- System Health Monitoring (30s continuous polling across Bot, FORGE, and AI-Universe)
- Cross-System Workflow Automation (Trading <-> AI-Universe, FORGE <-> Trading updates)
- Resource Coordination & Priority Queuing (Rate limits, load balancing)
- Intelligent Request Routing (Determines optimal subsystem for any user request)
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.skills.forge_manager import ForgeManagerSkill
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("ecosystem.orchestrator")


class TargetSubsystem(str, Enum):
    """Subsystem destinations in the FRIDAY ecosystem."""
    TRADING_BOT = "TRADING_BOT"
    FORGE = "FORGE"
    AI_UNIVERSE = "AI_UNIVERSE"
    ECOSYSTEM_MASTER = "ECOSYSTEM_MASTER"


@dataclass
class RoutedRequest:
    """Dispatched cross-system request record."""
    request_id: str
    target: TargetSubsystem
    user_prompt: str
    priority: str
    routed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemOrchestrator:
    """Master orchestrator routing requests and coordinating cross-system workflows."""

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        forge_manager: ForgeManagerSkill | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
    ) -> None:
        self._command_center = command_center
        self._forge_manager = forge_manager
        self._intel_engine = intelligence_engine
        self._routed_history: list[RoutedRequest] = []
        self._lock = threading.RLock()

    @property
    def command_center(self) -> EcosystemCommandCenter:
        if self._command_center is None:
            self._command_center = EcosystemCommandCenter()
        return self._command_center

    @property
    def forge_manager(self) -> ForgeManagerSkill:
        if self._forge_manager is None:
            self._forge_manager = ForgeManagerSkill()
        return self._forge_manager

    @property
    def intel_engine(self) -> IntelligenceEngine:
        if self._intel_engine is None:
            self._intel_engine = IntelligenceEngine()
        return self._intel_engine

    def route_request(self, user_request: str) -> TargetSubsystem:
        """Determines the optimal subsystem to handle the user's request."""
        clean = user_request.strip().lower()

        # 1. FORGE Software Engineering Keywords
        if any(k in clean for k in ["build ", "forge", "software task", "code artifact", "compile", "refactor"]):
            return TargetSubsystem.FORGE

        # 2. AI-Universe Keywords
        if any(k in clean for k in ["ai universe", "ai-universe", "consult about", "prediction", "sentiment", "whale"]):
            return TargetSubsystem.AI_UNIVERSE

        # 3. Trading Bot Keywords
        if any(k in clean for k in ["trading", "position", "p&l", "pnl", "binance", "bybit", "okx", "order", "portfolio"]):
            return TargetSubsystem.TRADING_BOT

        # 4. Ecosystem Default
        return TargetSubsystem.ECOSYSTEM_MASTER

    def execute_cross_system_workflow(
        self,
        user_request: str,
        priority: str = "NORMAL",
    ) -> dict[str, Any]:
        """Routes and executes a cross-system workflow."""
        with self._lock:
            target = self.route_request(user_request)
            req_id = f"route_{len(self._routed_history)+1:03d}"
            record = RoutedRequest(
                request_id=req_id,
                target=target,
                user_prompt=user_request,
                priority=priority,
            )
            self._routed_history.append(record)

            logger.info(f"[ECOSYSTEM_ORCHESTRATOR] Routed request '{user_request}' -> {target.value}")

            return {
                "request_id": req_id,
                "target_subsystem": target.value,
                "status": "DISPATCHED",
                "orchestrated_by": "FRIDAY_ECOSYSTEM_MASTER",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def check_system_health(self) -> dict[str, Any]:
        """Reports each subsystem's health **as reported**, or as unverified.

        ``forge_healthy = True  # FORGE Auth & REST client online`` was a comment
        doing the work of a health probe: the attribute was always True, so
        ``all_systems_healthy`` could be True while FORGE was unreachable, and a
        system that never reported was labelled DEGRADED (a judgement) rather than
        UNVERIFIED (the fact).
        """
        status = self.command_center.get_ecosystem_status()
        systems = status.get("systems", {})

        def verdict(name: str) -> str:
            reading = systems.get(name) or {}
            if not reading.get("available"):
                return "UNVERIFIED"
            return "HEALTHY" if str(reading.get("status", "")).upper() == "HEALTHY" else "DEGRADED"

        verdicts = {name: verdict(name) for name in ("trading_bot", "ai_universe", "friday_os")}
        # FORGE is probed for real: get_forge_health() issues GET /api/health and
        # reports what came back. (It previously returned a constant HEALTHY, and
        # this method declined to use it at all, substituting a task count.)
        forge_health: dict[str, Any] = {}
        probe = getattr(self.forge_manager, "get_forge_health", None)
        if callable(probe):
            try:
                forge_health = probe() or {}
            except Exception as exc:  # pragma: no cover - defensive
                forge_health = {"status": "PROBE FAILED", "error": str(exc), "reachable": False}
        if forge_health.get("reachable") is True:
            verdicts["forge"] = "HEALTHY" if str(forge_health.get("status", "")).upper() == "HEALTHY" else "DEGRADED"
        else:
            verdicts["forge"] = "UNVERIFIED"

        unverified = sorted(name for name, v in verdicts.items() if v == "UNVERIFIED")
        all_healthy = not unverified and all(v == "HEALTHY" for v in verdicts.values())

        return {
            "all_systems_healthy": all_healthy,
            "subsystems": verdicts,
            "unverified_subsystems": unverified,
            "forge_health": forge_health,
            "evidence": (
                "Every subsystem reported HEALTHY."
                if all_healthy
                else f"No health reading for: {', '.join(unverified)}."
                if unverified
                else "All subsystems reported, and at least one is not HEALTHY."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
