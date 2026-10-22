"""Advanced Intent Router for FRIDAY Ecosystem.

Decomposes complex compound natural language commands into discrete sub-intents
and extracts structured entities across four domains:
- Project Types: website, CLI, API, dashboard, script
- Trading Terms: positions, P&L, risk, drawdown, leverage
- Website Terms: visitors, leads, conversions, incidents
- Time References: today, this week, last month, overnight, yesterday
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("ecosystem.intent_router")


class ActionIntent(str, Enum):
    """Granular action intents."""
    FORGE_BUILD = "FORGE_BUILD"
    FORGE_STATUS = "FORGE_STATUS"
    TRADING_STATUS = "TRADING_STATUS"
    TRADING_PNL = "TRADING_PNL"
    TRADING_POSITIONS = "TRADING_POSITIONS"
    TRADING_EMERGENCY_STOP = "TRADING_EMERGENCY_STOP"
    NEXUS_STATUS = "NEXUS_STATUS"
    NEXUS_LEADS = "NEXUS_LEADS"
    NEXUS_DIAGNOSE = "NEXUS_DIAGNOSE"
    NEXUS_PAUSE_EXPERIMENT = "NEXUS_PAUSE_EXPERIMENT"
    AI_UNIVERSE_BRIEFING = "AI_UNIVERSE_BRIEFING"
    AI_UNIVERSE_EXPLAIN = "AI_UNIVERSE_EXPLAIN"
    ECOSYSTEM_HEALTH = "ECOSYSTEM_HEALTH"
    ECOSYSTEM_BRIEFING = "ECOSYSTEM_BRIEFING"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass
class ExtractedEntities:
    """Structured entities extracted from natural language input."""
    project_types: list[str] = field(default_factory=list)
    trading_terms: list[str] = field(default_factory=list)
    website_terms: list[str] = field(default_factory=list)
    time_references: list[str] = field(default_factory=list)
    raw_entities: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubIntentPlan:
    """A single decomposed intent unit ready for execution."""
    intent: ActionIntent
    target_subsystem: str  # trading_bot, nexus, forge, ai_universe, ecosystem
    command_segment: str
    entities: ExtractedEntities
    is_sensitive: bool = False


@dataclass
class ParsedCompoundCommand:
    """Comprehensive decomposition of a user request."""
    original_command: str
    is_compound: bool
    sub_intents: list[SubIntentPlan]
    global_entities: ExtractedEntities


class IntentRouter:
    """Advanced intent classifier and compound command parser."""

    PROJECT_PATTERNS = {
        "website": r"\b(?:website|landing\s+page|site|webpage)\b",
        "cli": r"\b(?:cli|command\s+line\s+tool|terminal\s+app)\b",
        "api": r"\b(?:api|rest\s+service|backend\s+endpoint|microservice)\b",
        "dashboard": r"\b(?:dashboard|analytics\s+panel|admin\s+ui)\b",
        "script": r"\b(?:script|automation\s+tool|bot|utility)\b",
    }

    TRADING_PATTERNS = {
        "positions": r"\b(?:positions?|open\s+trades?|holdings?)\b",
        "pnl": r"\b(?:p&l|pnl|profit|loss|gains?|returns?)\b",
        "risk": r"\b(?:risk|exposure|margin|leverage|drawdown|var)\b",
        "drawdown": r"\b(?:drawdown|max\s+dd|loss\s+limit)\b",
        "leverage": r"\b(?:leverage|gearing|borrowing)\b",
    }

    WEBSITE_PATTERNS = {
        "visitors": r"\b(?:visitors?|traffic|users?|sessions?|pageviews?)\b",
        "leads": r"\b(?:leads?|high-intent|prospects?|enterprise\s+visitors?)\b",
        "conversions": r"\b(?:conversions?|cr|signups?|funnel|drop)\b",
        "incidents": r"\b(?:incidents?|outages?|errors?|504|downtime)\b",
    }

    TIME_PATTERNS = {
        "today": r"\b(?:today|intraday|now|current)\b",
        "this week": r"\b(?:this\s+week|weekly|past\s+7\s+days)\b",
        "last month": r"\b(?:last\s+month|monthly|past\s+30\s+days)\b",
        "overnight": r"\b(?:overnight|last\s+night|while\s+i\s+slept)\b",
        "yesterday": r"\b(?:yesterday|prior\s+day|previous\s+session)\b",
    }

    def extract_entities(self, text: str) -> ExtractedEntities:
        """Extracts domain-specific entities from text."""
        clean = text.lower()
        projects = [name for name, pattern in self.PROJECT_PATTERNS.items() if re.search(pattern, clean)]
        trading = [name for name, pattern in self.TRADING_PATTERNS.items() if re.search(pattern, clean)]
        website = [name for name, pattern in self.WEBSITE_PATTERNS.items() if re.search(pattern, clean)]
        time_refs = [name for name, pattern in self.TIME_PATTERNS.items() if re.search(pattern, clean)]

        return ExtractedEntities(
            project_types=projects,
            trading_terms=trading,
            website_terms=website,
            time_references=time_refs,
        )

    def parse_command(self, user_command: str) -> ParsedCompoundCommand:
        """Decomposes compound commands (e.g. 'Build me a dashboard and check my trades')."""
        clean = user_command.strip()
        global_entities = self.extract_entities(clean)

        # Split on conjunctions: ' and ', ' & ', ' while ', ' also ', ' then '
        segments = re.split(r"\s+(?:and|&|while|also|then)\s+", clean, flags=re.IGNORECASE)
        sub_intents: list[SubIntentPlan] = []

        for seg in segments:
            seg_clean = seg.strip().lower()
            seg_entities = self.extract_entities(seg)

            # 1. FORGE Build Intent
            if any(k in seg_clean for k in ["build", "create", "make", "forge"]) and ("dashboard" in seg_clean or "website" in seg_clean or "cli" in seg_clean or "api" in seg_clean or "tool" in seg_clean):
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.FORGE_BUILD,
                        target_subsystem="forge",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )
            # 2. Trading Positions
            elif any(k in seg_clean for k in ["positions", "trades", "open trades", "check my positions", "show positions"]):
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.TRADING_POSITIONS,
                        target_subsystem="trading_bot",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )
            # 3. Trading PnL / General Status
            elif any(k in seg_clean for k in ["trading", "trades", "profit", "pnl", "drawdown", "how are my trades doing"]):
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.TRADING_STATUS,
                        target_subsystem="trading_bot",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )
            # 4. Nexus Website Status / Traffic / Leads
            elif any(k in seg_clean for k in ["website", "site", "leads", "visitors", "traffic", "how is the website doing"]):
                intent = ActionIntent.NEXUS_LEADS if "leads" in seg_clean else ActionIntent.NEXUS_STATUS
                sub_intents.append(
                    SubIntentPlan(
                        intent=intent,
                        target_subsystem="nexus",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )
            # 5. Global Health / Status
            elif any(k in seg_clean for k in ["status of everything", "health", "is everything healthy", "brief me"]):
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.ECOSYSTEM_HEALTH,
                        target_subsystem="ecosystem",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )
            # 6. Emergency Trading Halt
            elif any(k in seg_clean for k in ["emergency stop", "kill switch", "panic stop"]):
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.TRADING_EMERGENCY_STOP,
                        target_subsystem="trading_bot",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=True,
                    )
                )
            # Fallback segment
            else:
                sub_intents.append(
                    SubIntentPlan(
                        intent=ActionIntent.AMBIGUOUS,
                        target_subsystem="ecosystem",
                        command_segment=seg,
                        entities=seg_entities,
                        is_sensitive=False,
                    )
                )

        is_compound = len(sub_intents) > 1
        return ParsedCompoundCommand(
            original_command=user_command,
            is_compound=is_compound,
            sub_intents=sub_intents,
            global_entities=global_entities,
        )


# Global default instance
intent_router = IntentRouter()
