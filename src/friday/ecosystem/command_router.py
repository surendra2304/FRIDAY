# -*- coding: utf-8 -*-
"""Ecosystem Command Router for FRIDAY.

Intelligently parses user intents and routes voice/text commands to the appropriate subsystem:
- "Build me..." / "Forge, build..." -> FORGE Manager
- "How are my trades..." / "Trading status" -> Trading Bot
- "What does the market think..." / "AI prediction" -> AI-Universe
- "Status of everything" / "Brief me" -> Ecosystem Status Skill
- "Forge, build a trading dashboard" -> Cross-System Orchestrator
- Ambiguous commands -> Prompts operator for clarification
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple

from friday.core.logging import get_logger
from friday.ecosystem.cross_orchestrator import CrossSystemOrchestrator
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.forge_manager import ForgeManagerSkill

logger = get_logger("ecosystem.command_router")


class SubsystemRoute(str, Enum):
    """Subsystem routing targets."""
    TRADING_BOT = "TRADING_BOT"
    FORGE = "FORGE"
    AI_UNIVERSE = "AI_UNIVERSE"
    NEXUS = "NEXUS"
    SENTINEL = "SENTINEL"
    INTELX = "INTELX"
    ECOSYSTEM_STATUS = "ECOSYSTEM_STATUS"
    CROSS_SYSTEM_ORCHESTRATOR = "CROSS_SYSTEM_ORCHESTRATOR"
    AMBIGUOUS = "AMBIGUOUS"


class EcosystemCommandRouter:
    """Intelligent NLP router directing multi-domain commands to the target subsystem."""

    def __init__(
        self,
        cross_orchestrator: Optional[CrossSystemOrchestrator] = None,
        status_skill: Optional[EcosystemStatusSkill] = None,
        forge_manager: Optional[ForgeManagerSkill] = None,
    ) -> None:
        self.cross_orchestrator = cross_orchestrator or CrossSystemOrchestrator()
        self.status_skill = status_skill or EcosystemStatusSkill()
        self.forge_manager = forge_manager or ForgeManagerSkill()

    def route_command(self, user_command: str) -> Tuple[SubsystemRoute, Dict[str, Any]]:
        """Parses natural language command intent and determines routing destination."""
        clean = user_command.strip().lower()

        # 1. Multi-System Cross-Builds
        if any(k in clean for k in ["build a trading dashboard", "build a report generator", "build an alert system"]):
            template = (
                "TRADING_DASHBOARD" if "dashboard" in clean
                else "PERFORMANCE_REPORTER" if "report" in clean
                else "ALERT_SYSTEM"
            )
            return SubsystemRoute.CROSS_SYSTEM_ORCHESTRATOR, {"template": template, "command": user_command}

        # 2. Ecosystem Status / Briefing
        if any(k in clean for k in ["status of everything", "brief me", "ecosystem report", "health of my systems", "all systems status"]):
            return SubsystemRoute.ECOSYSTEM_STATUS, {"command": user_command}

        # 3. Research Library Search & Deep Research ("what do we know about", "research", "deep dive into", "quick scan on")
        if clean.startswith("what do we know about") or clean.startswith("what did we find about"):
            topic = clean.replace("what do we know about", "").replace("what did we find about", "").strip()
            return SubsystemRoute.INTELX, {"mode": "LIBRARY_FIRST_SEARCH", "topic": topic, "command": user_command}

        if clean.startswith("research ") or clean.startswith("deep dive into") or clean.startswith("quick scan on"):
            return SubsystemRoute.INTELX, {"mode": "NEW_RESEARCH", "command": user_command}

        # 4. Investigation ("investigate [target]") -> Contextual discrimination between Sentinel (security) and IntelX (general)
        if clean.startswith("investigate"):
            sec_keywords = ["cve", "vulnerability", "auth", "endpoint", "security", "attack surface", "firewall", "incident", "breach", "ssl", "tls"]
            is_sec = any(k in clean for k in sec_keywords)
            if is_sec:
                return SubsystemRoute.SENTINEL, {"action": "SECURITY_INVESTIGATION", "command": user_command}
            else:
                return SubsystemRoute.INTELX, {"action": "GENERAL_INVESTIGATION", "command": user_command}

        # 5. SENTINEL Autonomous Security
        if any(k in clean for k in ["run security scan", "security posture", "vulnerabilities", "attack surface", "sentinel", "threat intel", "audit security"]):
            return SubsystemRoute.SENTINEL, {"command": user_command}

        # 6. NEXUS Website & Growth Operations
        if any(k in clean for k in ["website status", "high-intent", "high intent", "leads", "conversions drop", "website incidents", "nexus", "pause the website experiment"]):
            return SubsystemRoute.NEXUS, {"command": user_command}

        # 7. FORGE Software Engineering
        if clean.startswith("build ") or clean.startswith("forge") or "cancel forge" in clean or "show what forge built" in clean:
            return SubsystemRoute.FORGE, {"command": user_command}

        # 8. Trading Bot
        if any(k in clean for k in ["how are my trades", "trading status", "portfolio risk", "emergency stop trading", "positions", "p&l"]):
            return SubsystemRoute.TRADING_BOT, {"command": user_command}

        # 9. AI-Universe
        if any(k in clean for k in ["what does the market think", "ai universe", "prediction", "whale flow", "market sentiment"]):
            return SubsystemRoute.AI_UNIVERSE, {"command": user_command}

        # 10. Ambiguous -> Require Clarification
        return SubsystemRoute.AMBIGUOUS, {
            "message": "I couldn't determine which subsystem your command targets (Trading Bot, Forge, AI-Universe, Nexus, Sentinel, or IntelX). Please clarify.",
            "command": user_command,
        }
