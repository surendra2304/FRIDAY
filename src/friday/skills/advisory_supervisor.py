"""Advisory Supervisor Skill for FRIDAY.

Supervises AI-Universe advisory activity for the Trading Bot on Binance Futures Testnet.
Monitors advisory logs, detects contested decisions (verdict=REJECT with high confidence > 0.7),
explains advisory rationale in plain language, and generates trading morning briefings.

Command Precedence Invariant:
Safety Gates (Trading Bot) > FRIDAY Commands (Supervisor) > AI-Universe Recommendations (Advisor).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.trading_bot_operator import TradingBotOperator

logger = get_logger("skills.advisory_supervisor")


@dataclass
class ContestedAdvisory:
    """Represents a contested advisory where AI confidence was high (>0.7) but the bot rejected it."""
    decision_id: str
    timestamp: str
    recommendation: str
    confidence: float
    rejection_reason: str
    parameter_adjustments: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class AdvisorySupervisorSkill(BaseSkill):
    """Supervises AI-Universe advisory activity for the Trading Bot."""

    name = "advisory_supervisor"
    description = (
        "Supervises AI-Universe advisory activity for the Algorithmic Trading Bot, "
        "detecting contested recommendations, explaining advisory rationale, and delivering trading morning briefings."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Trading Advisory Supervisor. You analyze the AI-Universe recommendations "
        "sent to the Trading Bot, identify contested decisions where high-confidence AI proposals "
        "were rejected by safety gates, explain risk boundaries, and compose spoken trading morning briefings."
    )
    match_patterns = [
        r"\b(?:what\s+did\s+ai[\s\-_]universe\s+recommend|what\s+did\s+ai\s+recommend)\b",
        r"\b(?:show\s+me\s+rejected\s+advisories|rejected\s+advisories|contested\s+advisories)\b",
        r"\b(?:what\s+parameters\s+has\s+the\s+ai\s+changed|advisory\s+state|ai\s+overlay)\b",
        r"\b(?:trading\s+morning\s+briefing|trading\s+briefing|trading\s+report)\b",
        r"\b(?:explain\s+advisory|explain\s+decision)\s+(?P<id>[\w\-]+)\b",
    ]

    def __init__(self, bot_operator: TradingBotOperator | None = None) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()

    def monitor_advisories(self, limit: int = 50) -> dict[str, Any]:
        """Fetch recent advisory log and detect contested decisions (REJECT + confidence > 0.70)."""
        recent_data = self.bot_operator.get_advisory_recent(limit=limit)
        advisories = recent_data.get("advisories", recent_data.get("recent_advisories", []))
        if isinstance(recent_data, list):
            advisories = recent_data

        contested_list: list[ContestedAdvisory] = []
        for a in advisories:
            verdict = str(a.get("verdict", "")).upper()
            confidence = float(a.get("confidence", 0.0))
            if verdict == "REJECT" and confidence > 0.70:
                decision_id = str(a.get("decision_id", a.get("id", a.get("run_id", "adv_unknown"))))
                ts = str(a.get("timestamp", a.get("created_at", "")))
                rec = str(a.get("recommendation", a.get("summary", "Adjust parameters")))
                reason = str(a.get("rejection_reason", a.get("reason", "Safety boundary threshold exceeded")))
                params = a.get("parameter_adjustments", a.get("parameters", {}))
                contested_list.append(
                    ContestedAdvisory(
                        decision_id=decision_id,
                        timestamp=ts,
                        recommendation=rec,
                        confidence=confidence,
                        rejection_reason=reason,
                        parameter_adjustments=params,
                        raw=a,
                    )
                )

        has_contested = len(contested_list) > 0
        if has_contested:
            summary = (
                f"Detected {len(contested_list)} contested advisory decisions where AI-Universe "
                f"confidently recommended parameter shifts that were blocked by Trading Bot safety gates."
            )
        else:
            summary = "No contested advisories detected. All recommendations conformed to safety boundaries."

        return {
            "total_advisories": len(advisories),
            "contested_count": len(contested_list),
            "contested_advisories": [c.__dict__ for c in contested_list],
            "has_contested": has_contested,
            "summary": summary,
        }

    def morning_trading_briefing(self) -> dict[str, Any]:
        """Compose a spoken briefing combining bot status, advisory summary, open positions, and equity."""
        bot_status = self.bot_operator.get_bot_status()
        advisory_summary = self.bot_operator.get_advisory_summary()

        pos_count = len(bot_status.open_positions)
        pnl_sign = "+" if bot_status.unrealized_pnl >= 0 else ""
        today_sign = "+" if bot_status.today_pnl >= 0 else ""

        positions_summary = ""
        if bot_status.open_positions:
            pos_lines = []
            for p in bot_status.open_positions:
                sym = p.get("symbol", "BTCUSDT")
                side = p.get("side", "LONG")
                pnl = p.get("unrealized_pnl", p.get("pnl", 0.0))
                pos_lines.append(f"{sym} {side} ({pnl:+.2f} USDT)")
            positions_summary = " Active positions: " + ", ".join(pos_lines) + "."
        else:
            positions_summary = " No open positions currently."

        spoken_text = (
            f"Trading Bot Morning Briefing: Status is {bot_status.status.lower()} on Binance Futures {bot_status.mode}. "
            f"Total equity stands at ${bot_status.equity:,.2f} USDT with today's PnL at {today_sign}${bot_status.today_pnl:,.2f} USDT "
            f"and unrealized PnL at {pnl_sign}${bot_status.unrealized_pnl:,.2f} USDT across {pos_count} position{'s' if pos_count != 1 else ''}. "
            f"{positions_summary} "
            f"{advisory_summary}"
        )

        return {
            "spoken_text": spoken_text,
            "equity": bot_status.equity,
            "today_pnl": bot_status.today_pnl,
            "unrealized_pnl": bot_status.unrealized_pnl,
            "position_count": pos_count,
            "positions": bot_status.open_positions,
            "advisory_summary": advisory_summary,
            "mode": bot_status.mode,
            "status": bot_status.status,
        }

    def explain_advisory(self, decision_id: str) -> dict[str, Any]:
        """Fetch and explain a specific advisory decision in plain language."""
        clean_id = decision_id.strip()
        recent_data = self.bot_operator.get_advisory_recent(limit=50)
        advisories = recent_data.get("advisories", recent_data.get("recent_advisories", []))
        if isinstance(recent_data, list):
            advisories = recent_data

        target = None
        for a in advisories:
            a_id = str(a.get("decision_id", a.get("id", a.get("run_id", ""))))
            if clean_id.lower() in a_id.lower():
                target = a
                break

        if not target:
            return {
                "found": False,
                "decision_id": clean_id,
                "explanation": f"Advisory decision '{clean_id}' was not found in recent logs.",
            }

        verdict = str(target.get("verdict", "UNKNOWN")).upper()
        confidence = float(target.get("confidence", 0.0))
        rec = target.get("recommendation", target.get("summary", "No recommendation text"))
        reason = target.get("rejection_reason", target.get("reason", "None provided"))
        evidence = target.get("key_evidence", target.get("evidence", []))
        params = target.get("parameter_adjustments", target.get("parameters", {}))

        evidence_str = "\n".join(f"  - {e}" for e in evidence) if evidence else "  - None recorded"
        params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "None"

        if verdict == "REJECT":
            explanation = (
                f"**Advisory Decision {clean_id} [REJECTED by Safety Gates]:**\n"
                f"• **AI-Universe Proposal:** {rec}\n"
                f"• **AI Confidence:** {int(confidence * 100)}%\n"
                f"• **Proposed Parameters:** {params_str}\n"
                f"• **Safety Gate Rejection Reason:** {reason}\n"
                f"• **Evidence Provided by AI:**\n{evidence_str}\n\n"
                f"*Verdict Explanation:* Even though AI-Universe recommended this adjustment, the Trading Bot's "
                f"immutable risk management safety gates rejected the change because it violated configured risk limits."
            )
        elif verdict == "APPLY":
            explanation = (
                f"**Advisory Decision {clean_id} [APPLIED]:**\n"
                f"• **AI-Universe Proposal:** {rec}\n"
                f"• **AI Confidence:** {int(confidence * 100)}%\n"
                f"• **Applied Parameters:** {params_str}\n"
                f"• **Evidence:**\n{evidence_str}\n\n"
                f"*Verdict Explanation:* The recommendation was within safety bounds and has been applied as an overlay."
            )
        else:
            explanation = (
                f"**Advisory Decision {clean_id} [{verdict}]:**\n"
                f"• **Proposal:** {rec}\n"
                f"• **Confidence:** {int(confidence * 100)}%\n"
                f"• **Parameters:** {params_str}\n"
            )

        return {
            "found": True,
            "decision_id": clean_id,
            "verdict": verdict,
            "confidence": confidence,
            "recommendation": rec,
            "rejection_reason": reason,
            "explanation": explanation,
            "raw": target,
        }

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes advisory supervision queries and briefings."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. Trading Morning Briefing
            if any(k in clean_req for k in ["trading morning briefing", "trading briefing", "trading report"]):
                briefing_data = self.morning_trading_briefing()
                step_results.append({"action": "morning_trading_briefing", "equity": briefing_data["equity"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=briefing_data["spoken_text"],
                    step_results=step_results,
                    metadata=briefing_data,
                )

            # 2. Explain Advisory Decision
            match_explain = re.search(r"\b(?:explain\s+advisory|explain\s+decision)\s+(?P<id>[\w\-]+)\b", clean_req)
            if match_explain:
                d_id = match_explain.group("id")
                exp_data = self.explain_advisory(d_id)
                step_results.append({"action": "explain_advisory", "decision_id": d_id, "found": exp_data["found"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=exp_data["explanation"],
                    step_results=step_results,
                    metadata=exp_data,
                )

            # 3. Contested Advisories (High Confidence >70% Blocked by Safety Gates)
            if any(k in clean_req for k in ["contested advisories", "contested advisory"]):
                mon_data = self.monitor_advisories()
                step_results.append({"action": "monitor_advisories", "contested_count": mon_data["contested_count"]})
                contested = mon_data.get("contested_advisories", [])

                if not contested:
                    output = "No contested AI-Universe advisories found in the recent log. All recommendations were either compliant or within risk thresholds."
                else:
                    lines = []
                    for c in contested[:5]:
                        conf = int(c["confidence"] * 100)
                        lines.append(
                            f"• **Decision [{c['decision_id']}]** ({conf}% Conf):\n"
                            f"  *AI Recommended:* {c['recommendation']}\n"
                            f"  *Bot Safety Gate Rejection:* {c['rejection_reason']}"
                        )
                    output = "**Contested AI-Universe Advisories (High AI Confidence >70% Blocked by Bot Safety Gates):**\n\n" + "\n\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=output,
                    step_results=step_results,
                    metadata=mon_data,
                )

            # 4. Rejected Advisories (All REJECT verdicts)
            if any(k in clean_req for k in ["rejected advisories", "show me rejected", "rejected recommendations"]):
                adv_data = self.bot_operator.get_advisory_recent(limit=25)
                advisories = adv_data.get("advisories", adv_data.get("recent_advisories", []))
                if isinstance(adv_data, list):
                    advisories = adv_data
                rejected = [a for a in advisories if str(a.get("verdict", "")).upper() == "REJECT"]
                step_results.append({"action": "get_advisory_recent_rejected", "count": len(rejected)})

                if not rejected:
                    msg = "No rejected AI-Universe advisories found in the recent log. All recommendations were either applied or hold."
                else:
                    lines = []
                    for a in rejected[:5]:
                        d_id = a.get("decision_id", a.get("id", "adv"))
                        conf = int(float(a.get("confidence", 0.0)) * 100)
                        rec = a.get("recommendation", a.get("summary", "Parameter change"))
                        reason = a.get("rejection_reason", a.get("reason", "Bounds violation"))
                        lines.append(f"• **[{d_id}]** ({conf}% Conf): {rec}\n  *Rejection Reason:* {reason}")
                    msg = "**Rejected AI-Universe Advisories (Filtered by Bot Safety Gates):**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata={"rejected": rejected},
                )

            # 4. General Advisory Query (What did AI-Universe recommend?)
            if any(k in clean_req for k in ["what did ai-universe recommend", "what did ai recommend", "ai recommendations"]):
                adv_data = self.bot_operator.get_advisory_recent(limit=10)
                advisories = adv_data.get("advisories", adv_data.get("recent_advisories", []))
                if isinstance(adv_data, list):
                    advisories = adv_data
                step_results.append({"action": "get_advisory_recent", "count": len(advisories)})

                if not advisories:
                    msg = "No recent AI-Universe advisory recommendations recorded in the trading log."
                else:
                    lines = []
                    for a in advisories[:5]:
                        verdict = str(a.get("verdict", "UNKNOWN")).upper()
                        conf = int(float(a.get("confidence", 0.0)) * 100)
                        rec = a.get("recommendation", a.get("summary", "Adjust parameters"))
                        reason = f" (Reason: {a.get('rejection_reason', a.get('reason', ''))})" if verdict == "REJECT" else ""
                        lines.append(f"• [{verdict} - {conf}% Conf] {rec}{reason}")
                    msg = "**Recent AI-Universe Advisory Decisions:**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata=adv_data,
                )

            # 5. Parameter Overlay Query
            if any(k in clean_req for k in ["parameters has the ai changed", "advisory state", "ai overlay", "overlay parameters"]):
                state = self.bot_operator.get_advisory_state()
                overlay = state.get("active_overlay", state.get("overlay", {}))
                step_results.append({"action": "get_advisory_state", "overlay": overlay})

                if not overlay:
                    msg = "The AI-Universe has not applied any active parameter modifications. Bot is running standard base parameters."
                else:
                    lines = [f"• **{k}**: {v}" for k, v in overlay.items()]
                    msg = "**Active AI-Universe Parameter Overlay:**\n" + "\n".join(lines)

                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=msg,
                    step_results=step_results,
                    metadata=state,
                )

            # Default fallback: delegate to morning trading briefing
            briefing_data = self.morning_trading_briefing()
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=briefing_data["spoken_text"],
                step_results=step_results,
                metadata=briefing_data,
            )

        except Exception as e:
            logger.error(f"[ADVISORY_SUPERVISOR] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Failed to execute advisory supervisor action: {e}",
                error=str(e),
                step_results=step_results,
            )
