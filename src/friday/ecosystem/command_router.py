"""Ecosystem Command Router for FRIDAY.

Routes high-level natural language intents to appropriate subsystem managers:
- "predict" / "forecast" -> FUTURIS
- "what will happen" -> FUTURIS
- "what if" / "scenario" -> FUTURIS
- "research" -> INTELX
- "what do we know about" -> INTELX (Library search first)
- "investigate" -> SENTINEL (if security) vs INTELX (if general)
- "build" / "compile" -> FORGE
- "trade" / "positions" -> TRADING_BOT
- "traffic" / "campaign" -> NEXUS
- "scan" / "security" -> SENTINEL
- "status of everything" -> ALL
"""

from enum import Enum
from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.cross_orchestrator import CrossSystemOrchestrator
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.forge_manager import ForgeManagerSkill
from friday.skills.futuris_manager import FuturisManagerSkill
from friday.skills.intelx_manager import IntelXManagerSkill
from friday.skills.nexus_manager import NexusManagerSkill
from friday.skills.sentinel_manager import SentinelManagerSkill

logger = get_logger("ecosystem.command_router")


class SubsystemRoute(Enum):
    TRADING_BOT = "trading_bot"
    FORGE = "forge"
    NEXUS = "nexus"
    SENTINEL = "sentinel"
    INTELX = "intelx"
    FUTURIS = "futuris"
    AI_UNIVERSE = "ai_universe"
    ECOSYSTEM_STATUS = "ecosystem_status"
    CROSS_SYSTEM_ORCHESTRATOR = "cross_system_orchestrator"
    ALL = "all"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class RouteResult(dict):
    """Result object supporting both dict access (res['route']) and tuple unpacking (route, ctx = res)."""

    def __init__(self, route: SubsystemRoute, data: dict[str, Any]):
        super().__init__(route=route.value, route_enum=route, **data)
        self.route = route
        self.data = data

    def __iter__(self):
        yield self.route
        yield self.data

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return (self.route, self.data)[key]
        return super().__getitem__(key)


class EcosystemCommandRouter:
    """Routes natural language queries across the 8-system ecosystem."""

    def __init__(
        self,
        cross_orchestrator: CrossSystemOrchestrator | None = None,
        status_skill: EcosystemStatusSkill | None = None,
        forge_manager: ForgeManagerSkill | None = None,
        nexus_manager: NexusManagerSkill | None = None,
        sentinel_manager: SentinelManagerSkill | None = None,
        intelx_manager: IntelXManagerSkill | None = None,
        futuris_manager: FuturisManagerSkill | None = None,
    ) -> None:
        self.cross_orch = cross_orchestrator or CrossSystemOrchestrator()
        self.status_skill = status_skill or EcosystemStatusSkill()
        self.forge = forge_manager or ForgeManagerSkill()
        self.nexus = nexus_manager or NexusManagerSkill()
        self.sentinel = sentinel_manager or SentinelManagerSkill()
        self.intelx = intelx_manager or IntelXManagerSkill()
        self.futuris = futuris_manager or FuturisManagerSkill()

    def route_command(self, query: str) -> RouteResult:
        """Determines target subsystem route and executes command."""
        q_lower = query.lower().strip()

        # Cross-system build (Forge build trading dashboard...)
        if "build a trading dashboard" in q_lower or "trading dashboard for my bot" in q_lower:
            return RouteResult(SubsystemRoute.CROSS_SYSTEM_ORCHESTRATOR, {"template": "TRADING_DASHBOARD", "query": query})

        if "scale up my website" in q_lower:
            eval_res = self.cross_orch.evaluate_website_scaling_decision()
            return RouteResult(SubsystemRoute.ALL, {"output": eval_res["formatted_summary"]})

        if "risk exposure" in q_lower:
            risk_res = self.cross_orch.assess_global_risk_exposure()
            return RouteResult(SubsystemRoute.ALL, {"output": risk_res["formatted_summary"]})

        # 1. Global Status / Health
        if any(k in q_lower for k in ["status of everything", "health of my systems", "brief me", "ecosystem status"]):
            res = self.status_skill.execute(query)
            return RouteResult(SubsystemRoute.ECOSYSTEM_STATUS, {"output": res.output})

        # AI Universe Intelligence Core
        if any(k in q_lower for k in ["ai universe", "ai-universe", "inference", "deliberation"]):
            return RouteResult(SubsystemRoute.AI_UNIVERSE, {"query": query})

        # 2. Futuris Forecasting & Scenario Simulation
        if any(k in q_lower for k in ["predict", "forecast", "what will happen", "what if", "run a scenario"]):
            res = self.futuris.execute(query)
            return RouteResult(SubsystemRoute.FUTURIS, {"output": res.output})

        # 3. IntelX Research & Knowledge
        if any(k in q_lower for k in ["research", "what do we know about", "deep dive"]):
            res = self.intelx.execute(query)
            return RouteResult(SubsystemRoute.INTELX, {"output": res.output})

        # 4. Sentinel Security & Investigation
        if any(k in q_lower for k in ["security scan", "vulnerabilities", "attack surface", "cve"]):
            res = self.sentinel.execute(query)
            return RouteResult(SubsystemRoute.SENTINEL, {"output": res.output})

        if "investigate" in q_lower:
            if any(sec in q_lower for sec in ["security", "breach", "cve", "vulnerability", "attack"]):
                res = self.sentinel.execute(query)
                return RouteResult(SubsystemRoute.SENTINEL, {"output": res.output})
            else:
                res = self.intelx.execute(query)
                return RouteResult(SubsystemRoute.INTELX, {"output": res.output})

        # 5. Trading Bot
        if any(k in q_lower for k in ["trade", "trades", "trading", "positions", "binance", "equity", "pnl"]):
            return RouteResult(SubsystemRoute.TRADING_BOT, {"query": query})

        # 6. Forge Software Builds
        if any(k in q_lower for k in ["build", "compile", "forge"]):
            res = self.forge.execute(query)
            return RouteResult(SubsystemRoute.FORGE, {"output": res.output})

        # 7. Nexus Website & Traffic
        if any(k in q_lower for k in ["nexus", "website", "traffic", "visitor", "visitors", "leads", "lead", "conversion"]):
            res = self.nexus.execute(query)
            return RouteResult(SubsystemRoute.NEXUS, {"output": res.output})

        # Fallback for unrecognized/ambiguous queries
        res = self.status_skill.execute(query)
        return RouteResult(SubsystemRoute.AMBIGUOUS, {"output": res.output})
