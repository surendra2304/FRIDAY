# -*- coding: utf-8 -*-
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
from typing import Any, Dict, Optional

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
    ALL = "all"
    UNKNOWN = "unknown"


class EcosystemCommandRouter:
    """Routes natural language queries across the 8-system ecosystem."""

    def __init__(
        self,
        cross_orchestrator: Optional[CrossSystemOrchestrator] = None,
        status_skill: Optional[EcosystemStatusSkill] = None,
        forge_manager: Optional[ForgeManagerSkill] = None,
        nexus_manager: Optional[NexusManagerSkill] = None,
        sentinel_manager: Optional[SentinelManagerSkill] = None,
        intelx_manager: Optional[IntelXManagerSkill] = None,
        futuris_manager: Optional[FuturisManagerSkill] = None,
    ) -> None:
        self.cross_orch = cross_orchestrator or CrossSystemOrchestrator()
        self.status_skill = status_skill or EcosystemStatusSkill()
        self.forge = forge_manager or ForgeManagerSkill()
        self.nexus = nexus_manager or NexusManagerSkill()
        self.sentinel = sentinel_manager or SentinelManagerSkill()
        self.intelx = intelx_manager or IntelXManagerSkill()
        self.futuris = futuris_manager or FuturisManagerSkill()

    def route_command(self, query: str) -> Dict[str, Any]:
        """Determines target subsystem route and executes command."""
        q_lower = query.lower().strip()

        # 1. Global Status / Health
        if any(k in q_lower for k in ["status of everything", "health of my systems", "brief me", "ecosystem status"]):
            res = self.status_skill.execute(query)
            return {"route": SubsystemRoute.ALL.value, "output": res.output}

        # 2. Futuris Forecasting & Scenario Simulation
        if any(k in q_lower for k in ["predict", "forecast", "what will happen", "what if", "run a scenario"]):
            res = self.futuris.execute(query)
            return {"route": SubsystemRoute.FUTURIS.value, "output": res.output}

        # 3. IntelX Research & Knowledge
        if any(k in q_lower for k in ["research", "what do we know about", "deep dive"]):
            res = self.intelx.execute(query)
            return {"route": SubsystemRoute.INTELX.value, "output": res.output}

        # 4. Sentinel Security & Investigation
        if any(k in q_lower for k in ["security scan", "vulnerabilities", "attack surface", "cve"]):
            res = self.sentinel.execute(query)
            return {"route": SubsystemRoute.SENTINEL.value, "output": res.output}

        if "investigate" in q_lower:
            if any(sec in q_lower for sec in ["security", "breach", "cve", "vulnerability", "attack"]):
                res = self.sentinel.execute(query)
                return {"route": SubsystemRoute.SENTINEL.value, "output": res.output}
            else:
                res = self.intelx.execute(query)
                return {"route": SubsystemRoute.INTELX.value, "output": res.output}

        # 5. Forge Software Builds
        if any(k in q_lower for k in ["build", "compile", "forge task"]):
            res = self.forge.execute(query)
            return {"route": SubsystemRoute.FORGE.value, "output": res.output}

        # 6. Nexus Website & Traffic
        if any(k in q_lower for k in ["nexus", "website traffic", "conversion rate"]):
            res = self.nexus.execute(query)
            return {"route": SubsystemRoute.NEXUS.value, "output": res.output}

        # 7. Cross-System Workflows
        if "scale up my website" in q_lower:
            eval_res = self.cross_orch.evaluate_website_scaling_decision()
            return {"route": SubsystemRoute.ALL.value, "output": eval_res["formatted_summary"]}

        if "risk exposure" in q_lower:
            risk_res = self.cross_orch.assess_global_risk_exposure()
            return {"route": SubsystemRoute.ALL.value, "output": risk_res["formatted_summary"]}

        # Fallback
        res = self.status_skill.execute(query)
        return {"route": SubsystemRoute.UNKNOWN.value, "output": res.output}
