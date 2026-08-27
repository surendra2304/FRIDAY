# -*- coding: utf-8 -*-
"""Natural Language Command Router for FRIDAY Ecosystem.

Performs intent classification, entity extraction (project types, trading terms, time references),
and multi-intent decomposition across FORGE, Trading Bot, AI-Universe, and Status skills.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple

from friday.core.logging import get_logger

logger = get_logger("ecosystem.nl_router")


class NLIntent(str, Enum):
    """Supported high-level natural language intents."""
    BUILD_TASK = "BUILD_TASK"
    TRADING_QUERY = "TRADING_QUERY"
    INTELLIGENCE_ANALYSIS = "INTELLIGENCE_ANALYSIS"
    STATUS_QUERY = "STATUS_QUERY"
    EMERGENCY_ACTION = "EMERGENCY_ACTION"
    MULTI_INTENT = "MULTI_INTENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class ExtractedEntities:
    """Entities extracted from user command."""
    project_type: Optional[str] = None  # website, CLI tool, API service, dashboard, script
    trading_terms: List[str] = field(default_factory=list)  # positions, p&l, risk, equity, leverage
    time_reference: Optional[str] = None  # today, this week, last month, overnight
    target_asset: Optional[str] = None  # btc, eth, sol
    custom_description: Optional[str] = None


@dataclass
class ParsedCommand:
    """Structured representation of a parsed natural language command."""
    raw_command: str
    primary_intent: NLIntent
    target_subsystems: List[str]  # forge, trading_bot, ai_universe, ecosystem_status
    entities: ExtractedEntities
    sub_commands: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0


class NLCommandRouter:
    """Intelligent natural language parser routing commands to ecosystem components."""

    def __init__(self) -> None:
        self._project_keywords = {
            "website": ["website", "landing page", "web page", "frontend", "portfolio"],
            "cli_tool": ["cli", "cli tool", "command line", "terminal utility", "argparse"],
            "api_service": ["api", "api service", "fastapi", "rest api", "backend service"],
            "dashboard": ["dashboard", "metrics panel", "live chart", "ui panel"],
            "script": ["script", "automation script", "python script", "reporter"],
        }
        self._trading_keywords = ["position", "positions", "p&l", "pnl", "profit", "loss", "equity", "risk", "leverage", "trade", "trades"]
        self._time_keywords = ["today", "this week", "last month", "overnight", "yesterday", "morning", "evening"]
        self._asset_keywords = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"]

    def extract_entities(self, text: str) -> ExtractedEntities:
        """Extracts structured entities from command text."""
        clean = text.lower()
        entities = ExtractedEntities()

        # 1. Project Type
        for ptype, aliases in self._project_keywords.items():
            if any(re.search(rf"\b{re.escape(a)}\b", clean) for a in aliases):
                entities.project_type = ptype
                break

        # 2. Trading Terms
        for term in self._trading_keywords:
            if re.search(rf"\b{re.escape(term)}\b", clean):
                entities.trading_terms.append(term)

        # 3. Time Reference
        for tref in self._time_keywords:
            if re.search(rf"\b{re.escape(tref)}\b", clean):
                entities.time_reference = tref
                break

        # 4. Target Asset
        for asset in self._asset_keywords:
            if re.search(rf"\b{re.escape(asset)}\b", clean):
                entities.target_asset = asset.upper()
                break

        entities.custom_description = text.strip()
        return entities

    def parse_command(self, user_command: str) -> ParsedCommand:
        """Analyzes command and determines single or multi-intent routing."""
        clean = user_command.strip().lower()
        entities = self.extract_entities(user_command)

        # Emergency Kill Switch
        if any(k in clean for k in ["emergency stop", "panic button", "halt trading", "kill switch"]):
            return ParsedCommand(
                raw_command=user_command,
                primary_intent=NLIntent.EMERGENCY_ACTION,
                target_subsystems=["trading_bot"],
                entities=entities,
                sub_commands=[{"target": "trading_bot", "action": "panic_kill_switch"}],
            )

        # Multi-Intent Detection (e.g. "Build me a trading dashboard and show my current positions")
        has_build = bool(re.search(r"\b(?:build|create|make|code|generate)\b", clean))
        has_trading = bool(entities.trading_terms or any(k in clean for k in ["trades", "bot", "exchange"]))
        has_status = bool(re.search(r"\b(?:status|how is|show me|report|brief)\b", clean))
        has_intel = bool(re.search(r"\b(?:analyze|think|research|predict|sentiment|whale)\b", clean))

        if " and " in clean or " & " in clean or " also " in clean:
            parts = re.split(r"\b(?:and|also|&)\b", clean)
            if len(parts) >= 2 and has_build and has_trading:
                sub_cmds = [
                    {"target": "forge", "action": "submit_build_request", "spec": parts[0].strip()},
                    {"target": "trading_bot", "action": "get_positions_or_status", "spec": parts[1].strip()},
                ]
                return ParsedCommand(
                    raw_command=user_command,
                    primary_intent=NLIntent.MULTI_INTENT,
                    target_subsystems=["forge", "trading_bot"],
                    entities=entities,
                    sub_commands=sub_cmds,
                )

        # Single Intent 1: FORGE Tasks
        if has_build or clean.startswith("forge"):
            return ParsedCommand(
                raw_command=user_command,
                primary_intent=NLIntent.BUILD_TASK,
                target_subsystems=["forge"],
                entities=entities,
                sub_commands=[{"target": "forge", "action": "submit_build_request", "prompt": user_command}],
            )

        # Single Intent 2: Trading Bot
        if has_trading and not has_intel:
            return ParsedCommand(
                raw_command=user_command,
                primary_intent=NLIntent.TRADING_QUERY,
                target_subsystems=["trading_bot"],
                entities=entities,
                sub_commands=[{"target": "trading_bot", "action": "query_trading", "terms": entities.trading_terms}],
            )

        # Single Intent 3: AI-Universe Intelligence
        if has_intel:
            return ParsedCommand(
                raw_command=user_command,
                primary_intent=NLIntent.INTELLIGENCE_ANALYSIS,
                target_subsystems=["ai_universe"],
                entities=entities,
                sub_commands=[{"target": "ai_universe", "action": "query_intelligence", "asset": entities.target_asset}],
            )

        # Single Intent 4: Status Query / Ecosystem Briefing
        if has_status or any(k in clean for k in ["status of everything", "brief me", "health"]):
            return ParsedCommand(
                raw_command=user_command,
                primary_intent=NLIntent.STATUS_QUERY,
                target_subsystems=["ecosystem_status"],
                entities=entities,
                sub_commands=[{"target": "ecosystem_status", "action": "get_ecosystem_status"}],
            )

        return ParsedCommand(
            raw_command=user_command,
            primary_intent=NLIntent.UNKNOWN,
            target_subsystems=["ecosystem_status"],
            entities=entities,
            sub_commands=[{"target": "ecosystem_status", "action": "fallback"}],
            confidence=0.4,
        )
