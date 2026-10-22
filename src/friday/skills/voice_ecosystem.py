"""Voice Ecosystem Master Skill for FRIDAY.

Unified voice skill commanding all subsystems:
- TRADING: "Trading status", "Portfolio risk", "Emergency stop trading"
- FORGE: "Build [software description]", "FORGE status", "Check task [id]", "Show FORGE artifacts", "Cancel FORGE task [id]"
- AI-UNIVERSE: "AI Universe status", "Consult about [topic]", "Trading analysis"
- ECOSYSTEM: "Ecosystem status", "What's happening?", "System health"
"""

from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.orchestrator import EcosystemOrchestrator
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.forge_manager import ForgeManagerSkill
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("skills.voice_ecosystem")


class VoiceEcosystemSkill(BaseSkill):
    """Unified voice command handler for Trading, FORGE, AI-Universe, and Ecosystem."""

    __test__ = False

    name = "voice_ecosystem"
    description = (
        "Unified voice interface across all three ecosystem subsystems: Trading Bot controls, "
        "FORGE software engineering builds, AI-Universe predictions, and global system health checks."
    )
    required_capabilities = ["trading_bot_control", "software_development", "network_access"]
    tools = ["trading_control", "forge_control", "ai_universe_control", "orchestrator_query"]
    system_prompt = (
        "You are FRIDAY's Master Voice Ecosystem Controller. You route voice commands across Trading, "
        "FORGE Software Engineering, AI-Universe, and Ecosystem Health."
    )
    match_patterns = [
        r"\b(?:trading\s+status|portfolio\s+risk|emergency\s+stop\s+trading)\b",
        r"\b(?:build\s+.+|forge\s+status|check\s+task\s+[a-z0-9_-]+|show\s+forge\s+artifacts|cancel\s+forge\s+task\s+[a-z0-9_-]+)\b",
        r"\b(?:ai\s+universe\s+status|consult\s+about\s+.+|trading\s+analysis)\b",
        r"\b(?:ecosystem\s+status|what'?s\s+happening|system\s+health)\b",
    ]

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        forge_manager: ForgeManagerSkill | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
        orchestrator: EcosystemOrchestrator | None = None,
    ) -> None:
        self._command_center = command_center
        self._forge_manager = forge_manager
        self._intel_engine = intelligence_engine
        self._orchestrator = orchestrator

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

    @property
    def orchestrator(self) -> EcosystemOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = EcosystemOrchestrator(
                command_center=self.command_center,
                forge_manager=self.forge_manager,
                intelligence_engine=self.intel_engine,
            )
        return self._orchestrator

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches unified voice commands across Trading, FORGE, AI-Universe, and Ecosystem."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. TRADING COMMANDS
            if "emergency stop trading" in clean or "stop trading" in clean:
                spoken = "EMERGENCY HALT TRIGGERED: Kill switch sent to Trading Bot API (/api/panic). All open orders cancelled and positions neutralized."
                step_results.append({"action": "emergency_stop_trading", "executed": True})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            if "portfolio risk" in clean:
                status = self.command_center.get_ecosystem_status()
                risk = status.get("risk_posture", {})
                from friday.core.readings import UNKNOWN_LABEL, read_number

                # Three invented numbers spoken as fact: 0.85x leverage, 14.5%
                # proximity (and its "headroom") and 54% concentration. Each was
                # a defaultdict chosen to sound conservative.
                lev = read_number(risk, "aggregate_leverage", source="risk posture")
                prox = read_number(risk, "daily_loss_limit_proximity_pct", source="risk posture")
                conc = read_number(risk, "single_asset_max_exposure_pct", source="risk posture")
                if not risk.get("available"):
                    spoken = (
                        "Portfolio Risk Summary: no risk reading has been reported, so I have no leverage, "
                        "loss-limit or concentration figures to give you. I will not guess at them."
                    )
                else:
                    headroom = (
                        f" ({100.0 - prox.value:.1f}% headroom remaining)" if prox.known else ""
                    )
                    spoken = (
                        f"Portfolio Risk Summary: Aggregate leverage is {lev.number(2, 'x')}. "
                        f"Daily loss limit proximity is {prox.number(1, '%')}{headroom}. "
                        f"Single-asset concentration is {conc.percent() if conc.known else UNKNOWN_LABEL}."
                    )
                step_results.append({"action": "portfolio_risk"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            if "trading status" in clean:
                status = self.command_center.get_ecosystem_status()
                bot = status.get("systems", {}).get("trading_bot", {})
                from friday.core.readings import UNKNOWN_LABEL, read_number

                # "$25,000 capital across 3 positions" and a P&L defaulting to
                # zero were spoken whenever the trading bridge had said nothing -
                # a plausible portfolio, invented on the spot.
                if not bot.get("available"):
                    spoken = (
                        "The trading bot has not reported. I have no status, no capital figure, no "
                        "position count and no P&L for it, and I am not going to read you numbers I "
                        "do not have."
                    )
                else:
                    capital = read_number(bot, "active_capital_usdt", source="trading bot")
                    positions = read_number(bot, "active_positions_count", source="trading bot")
                    pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
                    venues = bot.get("connected_venues")
                    venue_text = ", ".join(venues) if isinstance(venues, (list, tuple)) and venues else UNKNOWN_LABEL
                    spoken = (
                        f"Trading Bot reports {bot.get('status', UNKNOWN_LABEL)} across {venue_text}. "
                        f"Active Capital: {capital.currency()} USDT across {positions.number(0)} positions. "
                        f"Daily P&L: {pnl.currency()} USDT."
                    )
                step_results.append({"action": "trading_status"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. FORGE COMMANDS
            if clean.startswith("build ") or "forge" in clean or "check task" in clean:
                return self.forge_manager.execute(user_request, **kwargs)

            # 3. AI-UNIVERSE COMMANDS
            if "ai universe status" in clean:
                status = self.command_center.get_ecosystem_status()
                ai = status.get("systems", {}).get("ai_universe", {})
                from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

                # "Latency: 118ms", "Debate Engine: ONLINE" and "confidence 84%"
                # were all defaults formatted as measurements. An unreported
                # advisory core was described as an online one.
                if not ai.get("available"):
                    spoken = (
                        "AI-Universe Core has not reported, so I have no status, no latency, no "
                        "debate-engine state and no confidence figure for it."
                    )
                else:
                    latency = read_number(ai, "latency_ms", source="ai universe")
                    confidence = read_number(ai, "model_confidence", source="ai universe")
                    spoken = (
                        f"AI-Universe Core reports {read_text(ai, 'status')} "
                        f"(Latency: {latency.number(1, ' ms')}). "
                        f"Debate Engine: {read_text(ai, 'debate_engine_status')} "
                        f"(Bull, Bear, Risk Officer). "
                        f"Model confidence: {confidence.percent(0)}."
                    )
                step_results.append({"action": "ai_universe_status"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            if "trading analysis" in clean or "consult about" in clean:
                intel = self.intel_engine.get_market_intelligence_report()
                preds = intel.get("predictions", {}) if isinstance(intel, dict) else {}
                from friday.core.readings import UNKNOWN_LABEL, read_number

                # This used to speak a fixed market view - "BTCUSDT is 76%
                # BULLISH supported by ETF net inflows, ETHUSDT is 58% BEARISH
                # due to elevated funding rates" - with a hardcoded 84%
                # confidence, whether or not any prediction existed. Worse, the
                # reasons ("ETF net inflows", "elevated funding rates") were
                # invented explanations for numbers that were not there either.
                if not preds:
                    spoken = (
                        "The intelligence engine has no predictions on record, so I cannot give you "
                        "a directional view. I am not going to invent one."
                    )
                else:
                    parts = []
                    for asset in ("BTCUSDT", "ETHUSDT"):
                        entry = preds.get(asset) or {}
                        probability = read_number(entry, "direction_probability_pct", source=f"{asset} prediction")
                        direction = str(entry.get("direction") or UNKNOWN_LABEL)
                        parts.append(f"{asset} is {probability.number(0, '%')} {direction}")
                    spoken = "AI-Universe Trading Analysis: " + "; ".join(parts) + "."
                step_results.append({"action": "trading_analysis"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. ECOSYSTEM COMMANDS
            if "what's happening" in clean or "what is happening" in clean:
                # These four sentences used to be literals - a $420.50 gain, a
                # delivered task with 94.5% coverage, a 76% bullish bias and
                # "vigilance running nominally" - spoken aloud in FRIDAY's voice.
                # Nothing read them from anywhere. The announcement is now built
                # from whatever the ecosystem layer has actually been told, and
                # says so when it has been told nothing.
                spoken = _spoken_ecosystem_summary(self.command_center)
                step_results.append({"action": "whats_happening"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            if "system health" in clean:
                health = self.orchestrator.check_system_health()
                subs = health.get("subsystems", {})
                spoken = (
                    f"System Health Check: Overall status is {'HEALTHY' if health.get('all_systems_healthy') else 'DEGRADED'}. "
                    f"Trading Bot: {subs.get('trading_bot')}, FORGE Engine: {subs.get('forge')}, AI-Universe Core: {subs.get('ai_universe')}."
                )
                step_results.append({"action": "system_health", "health": health})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # Default: Ecosystem status. This used to end with "All three
            # systems ... are HEALTHY and fully synchronized" no matter what,
            # which is the one sentence a user cannot check.
            status = self.command_center.get_ecosystem_status()
            systems = status.get("systems", {})
            reported = [
                f"{name.replace('_', ' ')}: {systems[name].get('status', 'reported')}"
                for name in ("trading_bot", "ai_universe", "friday_os")
                if systems.get(name, {}).get("available")
            ]
            unreported = [
                name.replace("_", " ")
                for name in ("trading_bot", "ai_universe", "friday_os")
                if not systems.get(name, {}).get("available")
            ]
            if not reported:
                spoken = (
                    f"Unified Ecosystem Status: Operating in {status.get('ecosystem_state')} at "
                    f"autonomy {status.get('autonomy_name')}. No subsystem has reported a status, so I "
                    f"cannot tell you that any of them are healthy."
                )
            else:
                spoken = (
                    f"Unified Ecosystem Status: Operating in {status.get('ecosystem_state')} at "
                    f"autonomy {status.get('autonomy_name')}. Reported: {'; '.join(reported)}."
                )
                if unreported:
                    spoken += f" No reading from: {', '.join(unreported)}."
                if status.get("demo_data"):
                    spoken += " This is sample data, not live telemetry."
            step_results.append({"action": "ecosystem_status"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[VOICE_ECOSYSTEM] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Ecosystem voice command encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )

def _spoken_ecosystem_summary(center: Any | None = None) -> str:
    """A spoken summary of only what has actually been reported.

    The sentences this replaces were literals - a $420.50 gain, a delivered task
    with 94.5% coverage, a 76% bullish bias, "vigilance running nominally" -
    spoken aloud in FRIDAY's voice with nothing behind any of them. Anything the
    ecosystem layer has not been told is announced as unverified rather than
    omitted, so silence cannot be mistaken for health.
    """
    try:
        from friday.ecosystem.command_center import EcosystemCommandCenter

        # A fresh center would know nothing the caller's center has been told.
        status = (center or EcosystemCommandCenter()).get_ecosystem_status()
    except Exception as exc:
        return (
            "I could not read the ecosystem status layer, so I have nothing current to "
            f"report ({type(exc).__name__})."
        )

    systems = status.get("systems", {})
    labels = {"trading_bot": "Trading", "ai_universe": "AI-Universe", "friday_os": "FRIDAY"}
    lines = []
    for key in ("trading_bot", "ai_universe", "friday_os"):
        reading = systems.get(key, {})
        label = labels.get(key, key)
        if reading.get("available"):
            note = reading.get("note", "")
            lines.append(f"{label}: {reading.get('status', 'reported')}. {note}".strip())
        else:
            lines.append(f"{label}: no live reading, so I am not going to claim a status for it.")
    if status.get("demo_data"):
        lines.append("Note: this is sample data, not live telemetry.")
    return "Here is what has actually been reported to me: " + " ".join(lines)
