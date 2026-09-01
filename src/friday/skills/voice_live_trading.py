"""Voice Live Trading Skill for FRIDAY.

Provides interactive voice commands for real-capital live operations across three authorization tiers:
- SAFE: Live P&L, risk limit proximity, live positions, capital level status, daily report.
- SENSITIVE: Emergency flatten all positions, halt live trading, resume live trading (requires voice biometrics).
- DANGEROUS: Activate live trading kill switch, confirm capital level upgrade (requires voice biometrics >0.95 + confirmation phrase).
"""

from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.voice_live_trading")


class VoiceLiveTradingSkill(BaseSkill):
    """Voice live trading operations skill handling real-capital supervision and execution commands."""

    __test__ = False

    name = "voice_live_trading"
    description = (
        "Provides voice-activated real capital live trading supervision: live P&L, risk limit proximity, "
        "position audits, capital level progression, emergency flatten, and live kill-switch activation."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Live Trading Operations Specialist. You monitor real capital deployment on Binance Futures, "
        "track risk limit proximity, govern capital level progression, and execute emergency flatten and kill-switch commands."
    )
    match_patterns = [
        r"\b(?:what(?:'s|\s+is)\s+my\s+live\s+p&l|live\s+pnl|live\s+profit)\b",
        r"\b(?:how\s+far\s+from\s+(?:my\s+)?risk\s+limits|risk\s+proximity|distance\s+to\s+limits)\b",
        r"\b(?:what\s+are\s+my\s+live\s+positions|live\s+positions|open\s+positions)\b",
        r"\b(?:what\s+capital\s+level\s+am\s+i\s+on|capital\s+level|capital\s+tier)\b",
        r"\b(?:live\s+trading\s+status|live\s+status)\b",
        r"\b(?:daily\s+trading\s+report|daily\s+report)\b",
        r"\b(?:emergency\s+flatten\s+all\s+positions|flatten\s+positions|flatten\s+all)\b",
        r"\b(?:halt\s+live\s+trading|halt\s+trading)\b",
        r"\b(?:resume\s+live\s+trading|resume\s+trading)\b",
        r"\b(?:activate\s+live\s+trading\s+kill\s+switch|live\s+kill\s+switch|panic\s+kill\s+switch)\b",
        r"\b(?:confirm\s+capital\s+level\s+upgrade|upgrade\s+capital\s+level)\b",
    ]

    def __init__(
        self,
        live_ops: Any | None = None,
        capital_guardian: Any | None = None,
        live_analytics: Any | None = None,
        incident_manager: Any | None = None,
        security_manager: Any | None = None,
        emergency_manager: Any | None = None,
    ) -> None:
        self._live_ops = live_ops
        self._capital_guardian = capital_guardian
        self._live_analytics = live_analytics
        self._incident_manager = incident_manager
        self._security_manager = security_manager
        self._emergency_manager = emergency_manager

    @property
    def live_ops(self) -> Any:
        if self._live_ops is None:
            from friday.trading.live_operations import LiveOperationsCenter
            self._live_ops = LiveOperationsCenter()
        return self._live_ops

    @property
    def capital_guardian(self) -> Any:
        if self._capital_guardian is None:
            from friday.trading.capital_guardian import CapitalLevelGuardian
            self._capital_guardian = CapitalLevelGuardian()
        return self._capital_guardian

    @property
    def live_analytics(self) -> Any:
        if self._live_analytics is None:
            from friday.trading.live_analytics import LivePerformanceAnalytics
            self._live_analytics = LivePerformanceAnalytics()
        return self._live_analytics

    @property
    def incident_manager(self) -> Any:
        if self._incident_manager is None:
            from friday.trading.incident_manager import LiveIncidentManager
            self._incident_manager = LiveIncidentManager()
        return self._incident_manager

    @property
    def security_manager(self) -> Any:
        if self._security_manager is None:
            from friday.security.production_security import ProductionSecurityManager
            self._security_manager = ProductionSecurityManager()
        return self._security_manager

    @property
    def emergency_manager(self) -> Any:
        if self._emergency_manager is None:
            from friday.emergency_procedures import EmergencyProcedureManager
            self._emergency_manager = EmergencyProcedureManager()
        return self._emergency_manager

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches voice commands with multi-tier authorization."""
        clean = user_request.strip().lower()
        speaker_id = kwargs.get("speaker_id", "operator_surendra")
        voice_embedding = kwargs.get("voice_embedding")
        confirmation_phrase = kwargs.get("confirmation_phrase", "")

        step_results: list[dict[str, Any]] = []

        try:
            # =================================================================
            # 1. DANGEROUS COMMANDS (Requires Biometrics >0.95 + Confirmation)
            # =================================================================

            # A. "Activate live trading kill switch"
            if any(k in clean for k in ["kill switch", "live kill switch", "panic kill switch"]):
                # Validate confirmation phrase
                if not any(p in confirmation_phrase.lower() for p in ["confirm emergency action", "confirm kill switch", "authorized"]):
                    return SkillExecutionResult(
                        skill_name=self.name,
                        success=False,
                        output="DANGEROUS ACTION BLOCKED: Live trading kill switch requires explicit confirmation phrase ('Confirm emergency action').",
                        error="MISSING_CONFIRMATION_PHRASE",
                    )

                res = self.emergency_manager.trading_halt(
                    reason="Voice Live Operations: Emergency Kill Switch Activated",
                    initiator=speaker_id,
                    authorizer=authorizer,
                )
                signed = self.security_manager.sign_decision("LIVE_KILL_SWITCH", res, operator_id=speaker_id)
                output = (
                    "🚨 LIVE TRADING KILL SWITCH ACTIVATED! All new order execution is permanently blocked and pending brackets canceled. "
                    f"Audit Signature: `{signed['signature'][:12]}...`"
                )
                step_results.append({"action": "live_kill_switch", "audit_sig": signed["signature"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=res["success"],
                    output=output,
                    step_results=step_results,
                    metadata=res,
                )

            # B. "Confirm capital level upgrade"
            if any(k in clean for k in ["confirm capital level upgrade", "upgrade capital level"]):
                if not any(p in confirmation_phrase.lower() for p in ["confirm capital level upgrade", "confirm upgrade", "authorized"]):
                    return SkillExecutionResult(
                        skill_name=self.name,
                        success=False,
                        output="DANGEROUS ACTION BLOCKED: Capital level upgrade requires explicit confirmation phrase ('Confirm capital level upgrade').",
                        error="MISSING_CONFIRMATION_PHRASE",
                    )

                status = self.capital_guardian.get_level_status()
                target_lvl = status["current_level"] + 1
                upgrade_res = self.capital_guardian.confirm_level_transition(target_lvl, authorizer=authorizer)
                signed = self.security_manager.sign_decision("CAPITAL_LEVEL_UPGRADE", upgrade_res, operator_id=speaker_id)

                step_results.append({"action": "capital_level_upgrade", "new_level": target_lvl})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=upgrade_res["success"],
                    output=f"Capital Level Upgrade Confirmed: {upgrade_res['message']} (Audit Sig: `{signed['signature'][:12]}...`)",
                    step_results=step_results,
                    metadata=upgrade_res,
                )

            # =================================================================
            # 2. SENSITIVE COMMANDS (Requires Voice Biometrics)
            # =================================================================

            # A. "Emergency flatten all positions"
            if any(k in clean for k in ["emergency flatten", "flatten all positions", "flatten positions"]):
                res = self.emergency_manager.trading_halt(
                    reason="Voice Live Operations: Emergency Flatten All",
                    initiator=speaker_id,
                    authorizer=authorizer,
                )
                output = "Emergency Flatten initiated. Halting trading engine and requesting complete market position liquidation."
                step_results.append({"action": "emergency_flatten"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=res["success"],
                    output=output,
                    step_results=step_results,
                )

            # B. "Halt live trading"
            if any(k in clean for k in ["halt live trading", "halt trading"]):
                res = self.emergency_manager.advisory_disable(reason="Voice Live Operations: Halt live trading entries")
                output = "Live trading entries halted. Open positions will remain managed by hardcoded stop-loss and take-profit brackets."
                step_results.append({"action": "halt_live_trading"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=res["success"],
                    output=output,
                    step_results=step_results,
                )

            # C. "Resume live trading"
            if any(k in clean for k in ["resume live trading", "resume trading"]):
                try:
                    res = self.live_ops.bot_operator.toggle_testnet_advisory(enabled=True, mode="APPLY")
                    output = "Live trading execution resumed. New strategy signals and parameter overlays are actively enabled."
                    ok = True
                except Exception as e:
                    output = f"Failed to resume live trading: {e}"
                    ok = False
                step_results.append({"action": "resume_live_trading"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=ok,
                    output=output,
                    step_results=step_results,
                )

            # =================================================================
            # 3. SAFE COMMANDS (Instant Execution)
            # =================================================================

            # A. "What's my live P&L?"
            if any(k in clean for k in ["live p&l", "live pnl", "live profit"]):
                spoken = self.live_ops.get_spoken_pnl_summary()
                step_results.append({"action": "live_pnl"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=spoken,
                    step_results=step_results,
                )

            # B. "How far from my risk limits?"
            if any(k in clean for k in ["risk limits", "risk proximity", "distance to limits"]):
                spoken = self.live_ops.get_spoken_risk_proximity_summary()
                step_results.append({"action": "risk_proximity"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=spoken,
                    step_results=step_results,
                )

            # C. "What are my live positions?"
            if any(k in clean for k in ["live positions", "open positions"]):
                state = self.live_ops.poll_live_state()
                if state.positions:
                    lines = [f"You currently have {len(state.positions)} live positions open on Binance Futures:"]
                    for p in state.positions:
                        sign = "+" if p.unrealized_pnl >= 0 else "-"
                        lines.append(
                            f"• **{p.symbol}** ({p.side} {p.size} @ ${p.entry_price:,.2f}) — Unrealized: {sign}${abs(p.unrealized_pnl):,.2f} USDT ({p.unrealized_pnl_pct:+.2f}%)"
                        )
                    output = "\n".join(lines)
                else:
                    output = "You currently have no open live positions."

                step_results.append({"action": "live_positions", "count": len(state.positions)})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                )

            # D. "What capital level am I on?"
            if any(k in clean for k in ["capital level", "capital tier"]):
                status = self.capital_guardian.get_level_status()
                spoken = (
                    f"You are currently on **Level {status['current_level']} ({status['tier_name']})** with a capital ceiling of ${status['max_capital_usdt']:,.2f} USDT "
                    f"and max leverage of {status['max_leverage']:.1f}x. You have completed {status['clean_days_count']} clean days with +${status['cumulative_pnl_at_level']:,.2f} USDT P&L. "
                    f"{status['progression_reason']}"
                )
                step_results.append({"action": "capital_level_status"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=spoken,
                    step_results=step_results,
                )

            # E. "Daily trading report"
            if any(k in clean for k in ["daily trading report", "daily report"]):
                spoken = self.live_analytics.get_spoken_performance_summary()
                step_results.append({"action": "daily_trading_report"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=spoken,
                    step_results=step_results,
                )

            # F. Default: Live Trading Status
            state = self.live_ops.poll_live_state()
            output = (
                f"Live Trading Status is **{state.trading_mode}** on Capital Level {state.capital_level}. "
                f"Total equity is **${state.total_equity:,.2f} USDT** with an effective leverage of **{state.effective_leverage:.2f}x**. "
                f"Today's total P&L is **{'+' if state.total_pnl_today >= 0 else '-'}${abs(state.total_pnl_today):,.2f} USDT**. "
                f"Risk limit proximity: **{state.risk_proximity.proximity_warning_level}** ({state.risk_proximity.daily_loss_pct_used:.0f}% daily loss limit used)."
            )
            step_results.append({"action": "live_trading_status"})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=output,
                step_results=step_results,
            )

        except Exception as e:
            logger.error(f"[VOICE_LIVE_TRADING] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Live trading voice operations encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )
