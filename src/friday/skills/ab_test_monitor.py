"""A/B Test Monitor Skill for Trading Supervision.

Monitors and evaluates live A/B experiments on the Algorithmic Trading Bot
(Control baseline vs. Treatment with AI-Universe advisory overlays).
Provides real-time progress, statistical comparisons, outperformance explanations,
and comprehensive visual/markdown reports.

Every figure in this module is a *reading* taken from the trading bridge's
``/api/ab/status`` payload. Nothing here fills a missing reading with a
plausible-looking default: this file used to report a $10,000 arm equity, a
168-hour plan, a p-value of 0.05, "95% confidence", "2 blocked / 5 applied"
proposals and a specific "Dynamic Stop-Loss & Take-Profit tightening" overlay
that no endpoint had sent, and then explained the arms' divergence with them.
A missing figure is now ``None`` and renders as ``unknown (no reading)``, and a
cause that was not reported is not asserted.
"""

from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.readings import UNKNOWN_LABEL, format_money, format_number
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.skills.trading_bot_operator import TradingBotOperator

logger = get_logger("skills.ab_test_monitor")


def _num(mapping: Any, *keys: str) -> float | None:
    """The first reported numeric value among ``keys``, else None.

    Accepts numeric strings because bridges do send ``"1.45"``; booleans are not
    numbers here even though Python says they are.
    """
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


def _count(mapping: Any, *keys: str) -> int | None:
    """A reported trade/position count, or None when nothing was reported."""
    value = _num(mapping, *keys)
    return None if value is None else int(value)


def _text(mapping: Any, *keys: str) -> str | None:
    """A reported, non-empty string among ``keys``, else None."""
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


@dataclass
class ArmMetrics:
    """Performance metrics for an experimental arm (Control or Treatment).

    Each metric is Optional because an arm payload that omitted it has not
    reported it. ``trade_count`` is None too: an arm whose trade count was not
    sent has an *unknown* sample size, which is materially different from a
    proven zero.
    """

    arm_name: str
    equity: float | None
    total_return_pct: float | None
    sharpe_ratio: float | None
    win_rate_pct: float | None
    profit_factor: float | None
    max_drawdown_pct: float | None
    trade_count: int | None
    reported: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, arm_name: str, payload: Any) -> "ArmMetrics":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            arm_name=arm_name,
            equity=_num(data, "equity", "current_equity", "account_equity"),
            total_return_pct=_num(data, "total_return_pct", "return_pct"),
            sharpe_ratio=_num(data, "sharpe_ratio", "sharpe"),
            win_rate_pct=_num(data, "win_rate_pct", "win_rate"),
            profit_factor=_num(data, "profit_factor"),
            max_drawdown_pct=_num(data, "max_drawdown_pct", "drawdown_pct"),
            trade_count=_count(data, "trade_count", "trades"),
            reported=bool(data),
            raw=data,
        )

    def delta(self, other: "ArmMetrics", metric: str) -> float | None:
        """This arm's metric minus ``other``'s, or None if either is missing."""
        mine = getattr(self, metric)
        theirs = getattr(other, metric)
        if mine is None or theirs is None:
            return None
        return float(mine) - float(theirs)


class ABTestMonitorSkill(BaseSkill):
    """Supervises and reports on Trading Bot A/B experiments."""

    name = "ab_test_monitor"
    description = (
        "Monitors and evaluates trading bot A/B experiments, comparing Control vs Treatment performance, "
        "evaluating statistical significance, and generating comparative analysis reports."
    )
    required_capabilities = ["network_access", "trading_bot_control"]
    tools = ["trading_bot_query", "ai_universe_query"]
    system_prompt = (
        "You are FRIDAY's A/B Test Analyst. You evaluate live trading experiments comparing "
        "the Control baseline arm with the AI-Universe Treatment arm, checking statistical significance, "
        "drawdown boundaries, and delivering spoken briefings and reports."
    )
    match_patterns = [
        r"\b(?:how\s+is\s+(?:the\s+)?a[/-]?b\s+test\s+going|a[/-]?b\s+test\s+status|ab\s+status)\b",
        r"\b(?:what\s+are\s+(?:the\s+)?a[/-]?b\s+results|a[/-]?b\s+test\s+results|ab\s+results)\b",
        r"\b(?:explain\s+(?:the\s+)?a[/-]?b\s+difference|why\s+is\s+treatment\s+(?:outperforming|better)|explain\s+ab\s+test)\b",
        r"\b(?:generate\s+a[/-]?b\s+report|a[/-]?b\s+test\s+report|ab\s+report|create\s+ab\s+report)\b",
    ]

    def __init__(self, bot_operator: TradingBotOperator | None = None) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()

    def get_ab_status(self) -> dict[str, Any]:
        """Fetch current A/B test state, duration, progress, and trade volumes."""
        raw = self.bot_operator.get_ab_status()
        if not raw or raw.get("status") in ("NO_ACTIVE_TEST", "INACTIVE"):
            return {
                "active": False,
                "status": "NO_ACTIVE_TEST",
                "message": "There is currently no active A/B experiment running on the Trading Bot.",
                "raw": raw,
            }

        test_name = _text(raw, "test_name", "experiment_name") or "the unnamed experiment"
        status = str(raw.get("status") or "UNREPORTED").upper()
        elapsed_hours = _num(raw, "elapsed_hours", "duration_hours")
        planned_hours = _num(raw, "planned_hours", "target_duration_hours")
        progress_pct = _num(raw, "progress_pct")
        if progress_pct is None and elapsed_hours is not None and planned_hours:
            # Derived only from two readings that both exist.
            progress_pct = elapsed_hours / planned_hours * 100.0
        if progress_pct is not None:
            progress_pct = min(100.0, max(0.0, progress_pct))

        control_data = raw.get("control_arm", raw.get("control", {}))
        treatment_data = raw.get("treatment_arm", raw.get("treatment", {}))
        control_trades = _count(control_data, "trade_count", "trades")
        treatment_trades = _count(treatment_data, "trade_count", "trades")

        progress_clause = (
            f"Progress: {format_number(progress_pct, 1, '%')} complete "
            f"({format_number(elapsed_hours, 1, 'h')} of {format_number(planned_hours, 1, 'h')} planned). "
            if progress_pct is not None or elapsed_hours is not None or planned_hours is not None
            else "No elapsed or planned duration was reported, so I cannot state progress. "
        )
        sample_clause = (
            f"Total sample so far: {control_trades} Control trades vs {treatment_trades} Treatment trades."
            if control_trades is not None and treatment_trades is not None
            else "No trade counts were reported for the arms, so the sample size is unknown."
        )

        return {
            "active": True,
            "test_name": test_name,
            "status": status,
            "elapsed_hours": elapsed_hours,
            "planned_hours": planned_hours,
            "progress_pct": progress_pct,
            "control_trades": control_trades,
            "treatment_trades": treatment_trades,
            "control": control_data,
            "treatment": treatment_data,
            "spoken_summary": (
                f"A/B experiment '{test_name}' is reported as {status.lower()}. " + progress_clause + sample_clause
            ),
            "raw": raw,
        }

    def get_ab_results(self) -> dict[str, Any]:
        """Fetch and compare performance metrics and statistical significance between arms."""
        raw = self.bot_operator.get_ab_status()
        if not raw or raw.get("status") in ("NO_ACTIVE_TEST", "INACTIVE"):
            return {
                "active": False,
                "summary": "No active A/B test results to analyze.",
                "raw": raw,
            }

        control_dict = raw.get("control_arm", raw.get("control", {}))
        treatment_dict = raw.get("treatment_arm", raw.get("treatment", {}))
        stats_dict = raw.get("statistics", raw.get("stat_sig", {}))

        c_arm = ArmMetrics.from_payload("Control (Baseline)", control_dict)
        t_arm = ArmMetrics.from_payload("Treatment (AI-Universe Overlays)", treatment_dict)

        delta_return = t_arm.delta(c_arm, "total_return_pct")
        delta_str = (
            format_number(delta_return, 2, "%")
            if delta_return is not None
            else UNKNOWN_LABEL
        )

        p_value = _num(stats_dict, "p_value")
        # A p-value that was not computed cannot "achieve" significance, and a
        # missing p-value is not a 0.05 p-value with 95% confidence.
        stat_sig = None if p_value is None else bool(stats_dict.get("stat_sig_achieved", p_value < 0.05))
        confidence_pct = _num(stats_dict, "confidence")
        confidence_derived = False
        if confidence_pct is None and p_value is not None:
            # Derived, so it is labelled as derived rather than presented as a
            # figure the experiment computed.
            confidence_pct = (1.0 - p_value) * 100.0
            confidence_derived = True

        lead_arm = None
        if delta_return is not None:
            lead_arm = "Treatment" if delta_return > 0 else ("Control" if delta_return < 0 else "Neither arm")

        if lead_arm in (None, "Neither arm"):
            lead_clause = (
                "Neither arm is ahead: both reported the same total return."
                if lead_arm == "Neither arm"
                else "Neither arm can be called ahead because at least one arm did not report a total return."
            )
        else:
            lead_clause = f"The {lead_arm} arm is leading by {abs(delta_return):.2f}% excess return."

        def _arm_clause(arm: ArmMetrics) -> str:
            return (
                f"{arm.arm_name.split(' ')[0]} reported return "
                f"{format_number(arm.total_return_pct, 2, '%')}, profit factor "
                f"{format_number(arm.profit_factor, 2)} and Sharpe "
                f"{format_number(arm.sharpe_ratio, 2)}"
            )

        if stat_sig is None:
            significance_clause = (
                "No p-value was reported by the experiment, so statistical significance is unknown, "
                "not merely unachieved."
            )
        elif stat_sig:
            significance_clause = (
                f"Statistical significance was reported as achieved (p={p_value:.3f}"
                + (
                    f"; {format_number(confidence_pct, 1, '%')} confidence, derived from that p-value"
                    if confidence_derived and confidence_pct is not None
                    else (
                        f", {format_number(confidence_pct, 1, '%')} confidence reported"
                        if confidence_pct is not None
                        else ""
                    )
                )
                + ")."
            )
        else:
            significance_clause = (
                f"Statistical significance was reported as not yet achieved (p={p_value:.3f}"
                + (
                    f"; {format_number(confidence_pct, 1, '%')} confidence, derived from that p-value"
                    if confidence_derived and confidence_pct is not None
                    else (
                        f", {format_number(confidence_pct, 1, '%')} confidence reported"
                        if confidence_pct is not None
                        else ""
                    )
                )
                + ")."
            )

        return {
            "active": True,
            "control": dict(vars(c_arm)),
            "treatment": dict(vars(t_arm)),
            "delta_return_pct": delta_return,
            "delta_return_str": delta_str,
            "p_value": p_value,
            "stat_sig_achieved": stat_sig,
            "confidence_pct": confidence_pct,
            "confidence_derived": confidence_derived,
            "lead_arm": lead_arm,
            "spoken_summary": (
                f"A/B results: {lead_clause} {_arm_clause(t_arm)}; {_arm_clause(c_arm)}. {significance_clause}"
            ),
            "raw": raw,
        }

    def explain_ab_difference(self) -> dict[str, Any]:
        """Analyze the reported drivers of the performance delta between the arms.

        Only figures the endpoint actually sent are used. The module used to
        explain a divergence with a hardcoded ``{"blocked_by_safety": 2,
        "applied": 5}`` rejection count and a named "Dynamic Stop-Loss &
        Take-Profit tightening" overlay that no payload contained.
        """
        res_data = self.get_ab_results()
        if not res_data.get("active"):
            return {
                "active": False,
                "explanation": "No active A/B test running to analyze divergence.",
            }

        control = res_data["control"]
        treatment = res_data["treatment"]
        delta = res_data["delta_return_pct"]

        raw = res_data.get("raw", {})
        treatment_payload = raw.get("treatment_arm", raw.get("treatment", {}))
        overlays = (
            treatment_payload.get("active_overlays")
            or raw.get("active_overlays")
            or {}
        )
        rejection_stats = raw.get("rejection_stats") or {}

        overlay_bullets = (
            "\n".join(f"  - `{k}`: {v}" for k, v in overlays.items())
            if overlays
            else "  - No parameter overlay was reported for the treatment arm."
        )

        def _reported(arm: dict[str, Any], key: str) -> str:
            value = arm.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return UNKNOWN_LABEL
            return format_number(value, 0) if key == "trade_count" else format_number(value, 2)

        blocked = rejection_stats.get("blocked_by_safety")
        applied = rejection_stats.get("applied")
        rejection_clause = (
            f"{blocked} high-risk AI proposals were reported rejected by bot safety gates, "
            f"with {applied} applied."
            if isinstance(blocked, (int, float)) and isinstance(applied, (int, float))
            else "No safety-gate rejection statistics were reported for this experiment."
        )

        metrics_rows = "\n".join(
            f"| **{label}** | {_reported(control, key)} | {_reported(treatment, key)} |"
            for label, key in (
                ("Total Return %", "total_return_pct"),
                ("Profit Factor", "profit_factor"),
                ("Win Rate %", "win_rate_pct"),
                ("Sharpe Ratio", "sharpe_ratio"),
                ("Max Drawdown %", "max_drawdown_pct"),
                ("Executed Trades", "trade_count"),
            )
        )

        if delta is None:
            headline = (
                "**Neither arm's total return was reported in full**, so this analysis cannot say which arm "
                "is ahead. Only the reported readings are shown below; nothing is inferred."
            )
        elif delta > 0:
            headline = (
                f"**Outperformance Driver:** the **Treatment Arm** reports **+{delta:.2f}%** excess return over "
                f"Control on the figures the experiment sent."
            )
        elif delta < 0:
            headline = (
                f"**Underperformance Driver:** the **Control Arm** is currently ahead by **+{abs(delta):.2f}%** "
                f"reported return. The reported overlays are listed below; no cause is asserted that the payload "
                f"does not support."
            )
        else:
            headline = "**The two arms report identical total returns**, so there is no divergence to explain."

        analysis = (
            "### 🔬 A/B Performance Divergence Analysis\n\n"
            f"{headline}\n\n"
            "| Metric | Control (reported) | Treatment (reported) |\n"
            "| :--- | :---: | :---: |\n"
            f"{metrics_rows}\n\n"
            "**Reported Treatment Overlays:**\n"
            f"{overlay_bullets}\n\n"
            f"**Safety Gate Activity:** {rejection_clause}\n\n"
            f"**Statistical Assessment:** "
            + (
                f"p-value = `{res_data['p_value']:.3f}`."
                if res_data.get("p_value") is not None
                else "No p-value was reported, so no significance claim is made."
            )
        )

        return {
            "active": True,
            "delta_return_pct": delta,
            "p_value": res_data.get("p_value"),
            "explanation": analysis,
        }

    def generate_ab_report(self) -> dict[str, Any]:
        """Generate a complete Markdown and ASCII/table visualization report of the A/B test."""
        status_data = self.get_ab_status()
        if not status_data.get("active"):
            return {
                "active": False,
                "report": "No active A/B experiment data available to generate report.",
            }

        results_data = self.get_ab_results()
        explanation_data = self.explain_ab_difference()

        c = results_data["control"]
        t = results_data["treatment"]
        delta = results_data["delta_return_pct"]
        stat_sig = results_data["stat_sig_achieved"]
        sig_badge = (
            "✅ STATISTICALLY SIGNIFICANT"
            if stat_sig is True
            else ("⏳ IN PROGRESS (Significance Not Reached)" if stat_sig is False else "❔ UNKNOWN (no p-value reported)")
        )

        # The bars scale a reported return; an unreported return has no bar.
        def _bar(value: Any) -> str:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "(no return reported)"
            return "█" * max(1, int(max(0.0, float(value)) * 2))

        def _delta_cell(metric: str) -> str:
            d = t.get(metric) - c.get(metric) if isinstance(t.get(metric), (int, float)) and isinstance(c.get(metric), (int, float)) else None
            if d is None:
                return UNKNOWN_LABEL
            digits = 0 if metric == "trade_count" else 2
            sign = "+" if d >= 0 else ""
            return f"{sign}{d:.{digits}f}"

        report_md = (
            f"# 🧪 A/B Test Experiment Report: {status_data['test_name']}\n\n"
            f"**Status:** `{status_data['status']}` | **Progress:** "
            f"{format_number(status_data['progress_pct'], 1, '%')} "
            f"({format_number(status_data['elapsed_hours'], 1, 'h')} / "
            f"{format_number(status_data['planned_hours'], 1, 'h')} planned)\n"
            f"**Statistical Significance:** **{sig_badge}** "
            f"(`p = {format_number(results_data['p_value'], 3)}`, "
            f"{format_number(results_data['confidence_pct'], 1, '%')} confidence"
            f"{' derived from the p-value' if results_data.get('confidence_derived') else ' reported'})\n\n"
            f"## 📈 Comparative Equity & Return Visualization\n"
            f"```text\n"
            f"Control Arm   [{format_number(c['total_return_pct'], 2, '%')}]: {_bar(c['total_return_pct'])} "
            f"({format_money(c['equity'])})\n"
            f"Treatment Arm [{format_number(t['total_return_pct'], 2, '%')}]: {_bar(t['total_return_pct'])} "
            f"({format_money(t['equity'])})  <-- AI Overlays\n"
            f"```\n\n"
            f"## 📊 Metrics Comparison Table\n\n"
            f"| Metric | Control (Baseline) | Treatment (AI Overlays) | Delta / Improvement |\n"
            f"| :--- | :---: | :---: | :---: |\n"
            f"| **Current Equity** | {format_money(c['equity'])} USDT | {format_money(t['equity'])} USDT | "
            f"**{results_data['delta_return_str']} return delta** |\n"
            f"| **Total Return** | {format_number(c['total_return_pct'], 2, '%')} | "
            f"{format_number(t['total_return_pct'], 2, '%')} | **{format_number(delta, 2, '%')}** |\n"
            f"| **Profit Factor** | {format_number(c['profit_factor'], 2)} | {format_number(t['profit_factor'], 2)} | "
            f"**{_delta_cell('profit_factor')}** |\n"
            f"| **Win Rate** | {format_number(c['win_rate_pct'], 1, '%')} | {format_number(t['win_rate_pct'], 1, '%')} | "
            f"**{_delta_cell('win_rate_pct')}** |\n"
            f"| **Sharpe Ratio** | {format_number(c['sharpe_ratio'], 2)} | {format_number(t['sharpe_ratio'], 2)} | "
            f"**{_delta_cell('sharpe_ratio')}** |\n"
            f"| **Max Drawdown** | {format_number(c['max_drawdown_pct'], 2, '%')} | "
            f"{format_number(t['max_drawdown_pct'], 2, '%')} | **{_delta_cell('max_drawdown_pct')}** |\n"
            f"| **Executed Trades** | {c['trade_count'] if c['trade_count'] is not None else UNKNOWN_LABEL} | "
            f"{t['trade_count'] if t['trade_count'] is not None else UNKNOWN_LABEL} | "
            f"**{_delta_cell('trade_count')}** |\n\n"
            f"{explanation_data['explanation']}\n\n"
            f"## 🎯 Recommendation & Next Steps\n"
            + (
                "• **PROMOTION RECOMMENDED:** the treatment arm's excess return was reported statistically "
                f"significant (+{delta:.2f}%). Candidate for promotion to primary model.\n"
                if stat_sig is True and delta is not None
                else (
                    "• **CONTINUE EXPERIMENT:** the experiment has not reported reaching statistical "
                    "significance. Continue monitoring.\n"
                    if stat_sig is False
                    else "• **NO RECOMMENDATION POSSIBLE:** no p-value was reported, so this report cannot judge "
                    "whether the treatment arm is promotable.\n"
                )
            )
        )

        return {
            "active": True,
            "report_markdown": report_md,
            "status": status_data,
            "results": results_data,
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
        """Executes A/B testing queries, status checks, and report generation."""
        clean_req = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            # 1. Generate Full A/B Report
            if any(k in clean_req for k in ["generate ab report", "generate a/b report", "ab report", "a/b report", "ab test report"]):
                rep = self.generate_ab_report()
                if not rep.get("active"):
                    return SkillExecutionResult(
                        skill_name=self.name,
                        success=True,
                        output="There is currently no active A/B test running on the Trading Bot.",
                        step_results=[{"action": "generate_ab_report", "status": "INACTIVE"}],
                    )
                step_results.append({"action": "generate_ab_report", "status": "COMPLETED"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=rep["report_markdown"],
                    step_results=step_results,
                    metadata=rep,
                )

            # 2. Explain A/B Difference
            if any(k in clean_req for k in ["explain the ab difference", "explain the a/b difference", "why is treatment", "explain ab test"]):
                exp = self.explain_ab_difference()
                if not exp.get("active"):
                    return SkillExecutionResult(
                        skill_name=self.name,
                        success=True,
                        output="There is currently no active A/B test running on the Trading Bot.",
                        step_results=[{"action": "explain_ab_difference", "status": "INACTIVE"}],
                    )
                step_results.append({"action": "explain_ab_difference", "status": "COMPLETED"})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=exp["explanation"],
                    step_results=step_results,
                    metadata=exp,
                )

            # 3. What are the A/B results?
            if any(k in clean_req for k in ["what are the ab results", "what are the a/b results", "ab results", "a/b results", "ab test results"]):
                res = self.get_ab_results()
                if not res.get("active"):
                    return SkillExecutionResult(
                        skill_name=self.name,
                        success=True,
                        output="There is currently no active A/B test running on the Trading Bot.",
                        step_results=[{"action": "get_ab_results", "status": "INACTIVE"}],
                    )
                step_results.append({"action": "get_ab_results", "delta_return": res["delta_return_pct"]})
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output=res["spoken_summary"],
                    step_results=step_results,
                    metadata=res,
                )

            # 4. Default: How is the A/B test going? (Status)
            status = self.get_ab_status()
            if not status.get("active"):
                return SkillExecutionResult(
                    skill_name=self.name,
                    success=True,
                    output="There is currently no active A/B experiment running on the Trading Bot.",
                    step_results=[{"action": "get_ab_status", "status": "INACTIVE"}],
                )

            step_results.append({"action": "get_ab_status", "progress_pct": status["progress_pct"]})
            return SkillExecutionResult(
                skill_name=self.name,
                success=True,
                output=status["spoken_summary"],
                step_results=step_results,
                metadata=status,
            )

        except Exception as e:
            logger.error(f"[AB_TEST_MONITOR] Execution failure: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"I was unable to query A/B test metrics: {e}",
                error=str(e),
                step_results=step_results,
            )
