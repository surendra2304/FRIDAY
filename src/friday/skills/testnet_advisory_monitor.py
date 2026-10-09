"""Testnet Advisory Monitor Skill for Trading Supervision.

Supervises live Binance Futures Testnet AI advisories, tracking SHADOW vs APPLY
modes, comparing live testnet execution against paper trading baselines,
explaining testnet advisory decisions, and executing safety controls (mode toggle, parameter rollback).

Every number and every sentence about the market in this module is derived from
the trading bridge's payload. It used to be derived from defaults instead: a
$10,540.25 testnet equity, a 1.85% drawdown against a "safety threshold: 5.00%",
"Recent" as the last consultation, a 4.20%/3.85% paper-vs-testnet return pair, a
1.45/1.38 Sharpe pair, 100.0%/98.5% fill rates, and an execution diagnostic that
named "exchange matching engine queue times" as the primary driver of a slippage
gap nothing had measured. An absent reading is now ``None`` and the prose says so
instead of supplying a successor.
"""

import re
from typing import Any

from friday.core.logging import get_logger
from friday.core.readings import UNKNOWN_LABEL, format_money, format_number
from friday.core.types import AuthorizationDecision, SafetyLevel
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.trading_bot_operator import TradingBotOperator

logger = get_logger("skills.testnet_advisory_monitor")


def _num(mapping: Any, *keys: str) -> float | None:
    """The first reported numeric value among ``keys``, else None."""
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _text(mapping: Any, *keys: str) -> str | None:
    """The first reported, non-empty string among ``keys``, else None."""
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


class TestnetAdvisoryMonitorSkill(BaseSkill):
    """Supervises and manages live Binance Futures Testnet AI advisories."""

    __test__ = False

    name = "testnet_advisory_monitor"
    description = (
        "Supervises Binance Futures Testnet AI advisories, monitoring SHADOW vs APPLY modes, "
        "comparing testnet vs paper trading metrics, explaining decisions, and controlling safety toggles."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's Testnet Advisory Supervisor. You oversee live Binance Futures Testnet execution, "
        "monitoring whether AI-Universe advisories run in SHADOW or APPLY mode, analyzing execution slippage "
        "relative to paper trading, and enforcing safety controls."
    )
    match_patterns = [
        r"\b(?:how\s+is\s+(?:the\s+)?testnet\s+advisory\s+doing|testnet\s+advisory\s+status|testnet\s+status)\b",
        r"\b(?:what\s+are\s+(?:the\s+)?testnet\s+advisory\s+recommendations?|testnet\s+advisories|testnet\s+advisory\s+log)\b",
        r"\b(?:compare\s+testnet\s+(?:and|vs)\s+paper(?:\s+performance)?|testnet\s+vs\s+paper)\b",
        r"\b(?:explain\s+testnet\s+advisory\s+([a-zA-Z0-9_\-]+))\b",
        r"\b(?:disable\s+testnet\s+advisory|enable\s+testnet\s+advisory|toggle\s+testnet\s+advisory|switch\s+testnet\s+to\s+(?:apply|shadow))\b",
        r"\b(?:rollback\s+testnet\s+parameters|testnet\s+parameter\s+rollback)\b",
    ]

    def __init__(self, bot_operator: TradingBotOperator | None = None) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()

    def get_testnet_advisory_status(self) -> dict[str, Any]:
        """Fetch live testnet advisory status, active mode, health, and current overlays."""
        raw = self.bot_operator.get_testnet_advisory_status()
        if not raw:
            return {"active": False, "status": "UNAVAILABLE", "message": "Testnet advisory status unavailable."}

        enabled_raw = raw.get("enabled")
        enabled = enabled_raw if isinstance(enabled_raw, bool) else None
        mode = str(raw.get("mode") or "UNREPORTED").upper()
        health = str(raw.get("ai_universe_health") or raw.get("health") or "UNREPORTED").upper()
        equity = _num(raw, "equity", "current_equity")
        drawdown_pct = _num(raw, "drawdown_pct")
        max_drawdown_limit = _num(raw, "max_drawdown_limit", "max_drawdown_limit_pct")
        last_consult = _text(raw, "last_consult_time", "last_consult") or "not reported"
        active_overlay = raw.get("active_overlay") or {}
        open_positions = raw.get("open_positions") or []

        overlay_desc = (
            ", ".join(f"{k}={v}" for k, v in active_overlay.items())
            if active_overlay
            else "No active parameter overrides reported"
        )

        enabled_clause = (
            "ENABLED" if enabled is True else ("DISABLED" if enabled is False else "in an unreported enabled state")
        )
        threshold_clause = (
            f"(reported safety threshold: {format_number(max_drawdown_limit, 2, '%')})"
            if max_drawdown_limit is not None
            else "(no safety threshold was reported)"
        )

        spoken_text = (
            f"Testnet Advisory is reported as {enabled_clause} in {mode} mode. "
            f"AI-Universe health reads {health}. Testnet equity is {format_money(equity)} USDT with a drawdown of "
            f"{format_number(drawdown_pct, 2, '%')} {threshold_clause}. "
            f"Active parameter overlay: {overlay_desc}. "
            f"Last consultation: {last_consult}. Open positions reported: {len(open_positions)}."
        )

        return {
            "active": True,
            "enabled": enabled,
            "mode": mode,
            "health": health,
            "equity": equity,
            "drawdown_pct": drawdown_pct,
            "max_drawdown_limit": max_drawdown_limit,
            "last_consult_time": last_consult,
            "active_overlay": active_overlay,
            "open_positions": open_positions,
            "spoken_text": spoken_text,
            "raw": raw,
        }

    def get_testnet_advisory_log(self, limit: int = 10) -> dict[str, Any]:
        """Fetch recent testnet advisory evaluations and execution verdicts."""
        raw = self.bot_operator.get_testnet_advisory_log(limit=limit)
        advisories = raw.get("advisories", raw.get("log", [])) if isinstance(raw, dict) else raw
        if isinstance(raw, list):
            advisories = raw

        if not advisories:
            return {
                "active": True,
                "advisories": [],
                "formatted_text": "No recent Testnet advisory decisions recorded in log.",
            }

        lines = ["**Recent Testnet AI-Universe Advisory Decisions:**"]
        for adv in advisories[:limit]:
            dec_id = adv.get("decision_id") or "unspecified decision"
            verdict = str(adv.get("verdict") or "UNREPORTED").upper()
            mode = str(adv.get("mode") or "UNREPORTED").upper()
            conf_value = _num(adv, "confidence")
            conf = f"{conf_value * 100:.0f}% Conf" if conf_value is not None else "confidence not reported"
            rec = _text(adv, "recommendation") or "no recommendation text was sent"
            reason = adv.get("rejection_reason")

            tag = f"[{mode} | {verdict} - {conf}]"
            line = f"• `{dec_id}` {tag}: {rec}"
            if reason and verdict == "REJECT":
                line += f" *(Blocked by Safety Gate: {reason})*"
            lines.append(line)

        return {
            "active": True,
            "advisories": advisories,
            "formatted_text": "\n".join(lines),
        }

    def explain_testnet_advisory(self, decision_id: str) -> dict[str, Any]:
        """Provide detailed plain-language explanation of a specific testnet advisory decision."""
        log_data = self.get_testnet_advisory_log(limit=50)
        advisories = log_data.get("advisories", [])

        target = None
        for a in advisories:
            if str(a.get("decision_id", "")).lower() == decision_id.lower():
                target = a
                break

        if not target:
            return {
                "found": False,
                "explanation": f"Testnet advisory decision `{decision_id}` was not found in recent logs.",
            }

        verdict = str(target.get("verdict") or "UNREPORTED").upper()
        mode = str(target.get("mode") or "UNREPORTED").upper()
        conf_value = _num(target, "confidence")
        conf_clause = f"{conf_value * 100:.0f}% Confidence" if conf_value is not None else "confidence not reported"
        rec = _text(target, "recommendation") or "no recommendation text was sent with this decision"
        reason = target.get("rejection_reason")
        params = target.get("parameter_adjustments") or {}
        evidence = target.get("key_evidence") or []

        param_str = ", ".join(f"`{k}` -> `{v}`" for k, v in params.items()) if params else "none reported"
        # "Standard market conditions" used to be printed here as the evidence
        # for a decision that shipped no evidence.
        evidence_str = "\n".join(f"  - {e}" for e in evidence) if evidence else "  - No market evidence was reported with this decision."

        if verdict == "APPLY":
            gate_line = (
                "✅ **APPROVED:** the advisory was recorded as applied. The bridge did not report which safety "
                "limits were checked, so this explanation does not assert that all of them were."
            )
        elif verdict == "REJECT":
            gate_line = f"🛡️ **REJECTED by Safety Gate:** {reason or 'no rejection reason was reported.'}"
        else:
            gate_line = f"⏸️ **{verdict}:** no apply or reject verdict was reported for this decision."

        explanation = (
            f"### 📋 Testnet Advisory Explanation: `{decision_id}`\n\n"
            f"**Execution Mode:** `{mode}` | **Verdict:** **{verdict}** ({conf_clause})\n\n"
            f"**AI-Universe Recommendation:**\n> {rec}\n\n"
            f"**Proposed Parameters:** {param_str}\n\n"
            f"**Key Market Evidence:**\n{evidence_str}\n\n"
            f"**Safety Gate Assessment:**\n{gate_line}\n"
        )

        return {
            "found": True,
            "decision_id": decision_id,
            "verdict": verdict,
            "mode": mode,
            "explanation": explanation,
            "raw": target,
        }

    def compare_testnet_paper(self) -> dict[str, Any]:
        """Compare live Binance Futures Testnet execution metrics against paper trading / shadow baselines."""
        raw = self.bot_operator.get_testnet_paper_comparison()
        if not raw:
            return {
                "active": False,
                "comparison_text": "Testnet vs Paper trading comparative data is currently unavailable.",
            }

        paper = raw.get("paper_trading", raw.get("paper", {}))
        testnet = raw.get("testnet_live", raw.get("testnet", {}))

        p_ret = _num(paper, "total_return_pct", "return_pct")
        t_ret = _num(testnet, "total_return_pct", "return_pct")
        p_sharpe = _num(paper, "sharpe_ratio", "sharpe")
        t_sharpe = _num(testnet, "sharpe_ratio", "sharpe")
        p_slip = _num(paper, "avg_slippage_bps", "slippage_bps")
        t_slip = _num(testnet, "avg_slippage_bps", "slippage_bps")
        p_fill = _num(paper, "fill_rate_pct", "fill_rate")
        t_fill = _num(testnet, "fill_rate_pct", "fill_rate")
        p_dd = _num(paper, "max_drawdown_pct", "drawdown_pct")
        t_dd = _num(testnet, "max_drawdown_pct", "drawdown_pct")

        delta_ret = (t_ret - p_ret) if (t_ret is not None and p_ret is not None) else None
        slip_diff = (t_slip - p_slip) if (t_slip is not None and p_slip is not None) else None

        def _delta(a: float | None, b: float | None, digits: int, suffix: str = "") -> str:
            if a is None or b is None:
                return UNKNOWN_LABEL
            return format_number(a - b, digits, suffix)

        table_md = (
            f"### ⚖️ Testnet Live Execution vs. Paper Trading Comparison\n\n"
            f"| Metric | Paper Trading (Simulated) | Testnet Live (Binance Futures) | Delta / Variance |\n"
            f"| :--- | :---: | :---: | :---: |\n"
            f"| **Total Return** | {format_number(p_ret, 2, '%')} | {format_number(t_ret, 2, '%')} | "
            f"**{_delta(t_ret, p_ret, 2, '%')}** |\n"
            f"| **Sharpe Ratio** | {format_number(p_sharpe, 2)} | {format_number(t_sharpe, 2)} | "
            f"**{_delta(t_sharpe, p_sharpe, 2)}** |\n"
            f"| **Avg Slippage** | {format_number(p_slip, 1, ' bps')} | {format_number(t_slip, 1, ' bps')} | "
            f"**{_delta(t_slip, p_slip, 1, ' bps')}** |\n"
            f"| **Fill Rate** | {format_number(p_fill, 1, '%')} | {format_number(t_fill, 1, '%')} | "
            f"**{_delta(t_fill, p_fill, 1, '%')}** |\n"
            f"| **Max Drawdown** | {format_number(p_dd, 2, '%')} | {format_number(t_dd, 2, '%')} | "
            f"**{_delta(t_dd, p_dd, 2, '%')}** |\n\n"
            f"**Execution Diagnostic:** "
            + (
                f"Live testnet return variance is `{delta_ret:+.2f}%` relative to paper, and the reported slippage "
                f"gap is `{slip_diff:+.1f} bps`. The endpoint reports the gap, not its cause; no cause is asserted "
                f"here."
                if delta_ret is not None and slip_diff is not None
                else (
                    f"Live testnet return variance is `{delta_ret:+.2f}%` relative to paper. "
                    f"The slippage gap cannot be computed because at least one average slippage figure was not reported."
                    if delta_ret is not None
                    else "Neither a full return pair nor a full slippage pair was reported, so no diagnostic is offered."
                )
            )
        )

        return {
            "active": True,
            "paper": paper,
            "testnet": testnet,
            "delta_return_pct": delta_ret,
            "slippage_diff_bps": slip_diff,
            "comparison_text": table_md,
            "raw": raw,
        }

    def toggle_advisory_mode(
        self, enabled: bool = True, mode: str = "SHADOW", authorizer: Any | None = None
    ) -> dict[str, Any]:
        """Toggles testnet advisory enabled state or switches mode between SHADOW and APPLY."""
        if authorizer:
            auth_res = authorizer.authorize(
                action="toggle_testnet_advisory",
                resource=f"testnet_advisory:{mode}",
                safety_level=SafetyLevel.SENSITIVE,
                context={"enabled": enabled, "mode": mode},
            )
            if auth_res.decision == AuthorizationDecision.DENIED:
                return {
                    "success": False,
                    "message": f"Authorization denied: {auth_res.reason}",
                    "error": "Authorization Denied",
                }

        res = self.bot_operator.toggle_testnet_advisory(enabled=enabled, mode=mode)
        # The response used to be discarded, so a bridge that answered
        # {"status": "ERROR"} was still announced as "successfully updated".
        reported_error = None
        if isinstance(res, dict):
            reported_error = res.get("error") or (
                res.get("status") if str(res.get("status", "")).upper() in ("ERROR", "FAILED", "FAILURE") else None
            )
        if reported_error:
            return {
                "success": False,
                "message": f"The trading bridge did not apply the mode change: {reported_error}",
                "error": str(reported_error),
                "result": res,
            }

        reported_mode = None
        if isinstance(res, dict):
            reported_mode = res.get("mode")
        return {
            "success": True,
            "message": (
                f"Testnet advisory mode toggle sent: {mode} (Enabled: {enabled})."
                + (f" The bridge confirmed mode {reported_mode}." if reported_mode else " The bridge did not echo the resulting mode.")
            ),
            "result": res,
        }

    def rollback_parameters(self, authorizer: Any | None = None) -> dict[str, Any]:
        """Executes emergency rollback of all testnet parameter overlays to baseline."""
        if authorizer:
            auth_res = authorizer.authorize(
                action="rollback_testnet_parameters",
                resource="testnet_parameters",
                safety_level=SafetyLevel.SENSITIVE,
                context={"action": "ROLLBACK"},
            )
            if auth_res.decision == AuthorizationDecision.DENIED:
                return {
                    "success": False,
                    "message": f"Authorization denied: {auth_res.reason}",
                    "error": "Authorization Denied",
                }

        res = self.bot_operator.rollback_testnet_parameters()
        reported_error = None
        if isinstance(res, dict):
            reported_error = res.get("error") or (
                res.get("status") if str(res.get("status", "")).upper() in ("ERROR", "FAILED", "FAILURE") else None
            )
        if reported_error:
            return {
                "success": False,
                "message": f"The trading bridge did not roll back the parameter overlays: {reported_error}",
                "error": str(reported_error),
                "result": res,
            }

        return {
            "success": True,
            "message": (
                "Rollback request sent: the bridge was asked to revert all testnet parameter overlays to the "
                "baseline. Confirm the active overlay in a status query to see what it actually applied."
            ),
            "result": res,
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
        """Dispatches natural language user queries for testnet advisory supervision."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. Rollback testnet parameters
            if any(k in clean_req for k in ["rollback testnet parameters", "testnet parameter rollback"]):
                roll = self.rollback_parameters(authorizer=authorizer)
                step_results.append({"action": "rollback_testnet_parameters", "success": roll["success"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=roll["success"],
                    output=roll["message"],
                    step_results=step_results,
                    metadata=roll,
                )

            # 2. Toggle/disable/enable testnet advisory
            if any(k in clean_req for k in ["disable testnet advisory", "enable testnet advisory", "toggle testnet advisory", "switch testnet to"]):
                enabled = "disable" not in clean_req
                mode = "APPLY" if "apply" in clean_req else "SHADOW"
                tog = self.toggle_advisory_mode(enabled=enabled, mode=mode, authorizer=authorizer)
                step_results.append({"action": "toggle_testnet_advisory", "mode": mode, "enabled": enabled})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=tog["success"],
                    output=tog["message"],
                    step_results=step_results,
                    metadata=tog,
                )

            # 3. Compare testnet and paper performance
            if any(k in clean_req for k in ["compare testnet and paper", "testnet vs paper", "compare testnet vs paper"]):
                comp = self.compare_testnet_paper()
                step_results.append({"action": "compare_testnet_paper", "delta_return": comp.get("delta_return_pct")})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=comp["comparison_text"],
                    step_results=step_results,
                    metadata=comp,
                )

            # 4. Explain testnet advisory [decision_id]
            match_exp = re.search(r"\bexplain\s+testnet\s+advisory\s+([a-zA-Z0-9_\-]+)\b", clean_req)
            if match_exp:
                dec_id = match_exp.group(1)
                exp = self.explain_testnet_advisory(dec_id)
                step_results.append({"action": "explain_testnet_advisory", "decision_id": dec_id, "found": exp["found"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=exp["explanation"],
                    step_results=step_results,
                    metadata=exp,
                )

            # 5. What are the testnet advisory recommendations? (Log)
            if any(k in clean_req for k in ["testnet advisory recommendations", "testnet advisories", "testnet advisory log"]):
                log_data = self.get_testnet_advisory_log()
                step_results.append({"action": "get_testnet_advisory_log", "count": len(log_data["advisories"])})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=log_data["formatted_text"],
                    step_results=step_results,
                    metadata=log_data,
                )

            # 6. Default: How is the testnet advisory doing? (Status)
            status_data = self.get_testnet_advisory_status()
            step_results.append({"action": "get_testnet_advisory_status", "mode": status_data["mode"]})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=status_data["spoken_text"],
                step_results=step_results,
                metadata=status_data,
            )

        except Exception as e:
            logger.error(f"[TESTNET_ADVISORY_MONITOR] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Failed to query testnet advisory: {e}",
                error=str(e),
                step_results=step_results,
            )
