"""Ecosystem Master Dashboard for FRIDAY.

Provides a unified single-pane-of-glass dashboard for all three managed systems:
- Algorithmic Trading Bot (Live status, open positions, risk metrics)
- FORGE Autonomous SWE Engine (Active builds, test coverage, artifacts)
- AI-Universe Core (Consultant health, active debates, predictions)
- Cross-System Activity Feed (Chronological color-coded feed)
- Emergency Controls (Kill trading, cancel builds, disconnect advisory)
"""

from datetime import datetime, timezone
from typing import Any

from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.skills.forge_manager import ForgeManagerSkill
from friday.trading.intelligence_engine import IntelligenceEngine


#: Traffic lights for the dashboard. Module constants rather than escapes inside
#: an f-string expression: a backslash in that position is a SyntaxError before
#: Python 3.12.
_GREEN = "\U0001f7e2"
_RED = "\U0001f534"
_GREY = "\u26aa"


class EcosystemMasterDashboard:
    """Renders real-time executive dashboard across Trading Bot, FORGE, and AI-Universe."""

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        forge_manager: ForgeManagerSkill | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
    ) -> None:
        self._command_center = command_center
        self._forge_manager = forge_manager
        self._intel_engine = intelligence_engine

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

    def render_dashboard(self) -> str:
        """Renders comprehensive Markdown dashboard."""
        now_iso = datetime.now(timezone.utc).isoformat()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        systems = status.get("systems", {})
        bot = systems.get("trading_bot", {})
        ai = systems.get("ai_universe", {})
        risk = status.get("risk_posture", {})

        # FORGE data
        forge_tasks = self.forge_manager._tasks
        forge_active = sum(1 for t in forge_tasks.values() if t.status == "IN_PROGRESS")
        forge_completed = sum(1 for t in forge_tasks.values() if t.status == "COMPLETED")
        avg_coverage = (
            sum(t.test_coverage_pct for t in forge_tasks.values()) / len(forge_tasks)
            if forge_tasks else 0.0
        )

        # Cross-system activity feed.
        #
        # These five lines used to be literals. Every number in them - the P&L,
        # `forge_task_01` and its artifact path, the "76% Bullish on BTCUSDT"
        # prediction, the 65.0% build and the "zero safety breaches" - was
        # invented text rendered into an executive dashboard under a live
        # timestamp, next to real values read from the command centre. A reader
        # has no way to tell which half was measured. Each line is now derived
        # from state that exists, and a line with nothing behind it says so.
        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        feed_pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        feed_positions = read_number(bot, "active_positions_count", source="trading bot")
        if bot.get("available"):
            trading_line = (
                f"• 🔵 **[TRADING]** Reported daily P&L {feed_pnl.currency()} USDT "
                f"across {feed_positions.number(0)} positions (source: command centre)."
            )
        else:
            trading_line = (
                "• 🔵 **[TRADING]** No reading from the trading bot: "
                "P&L, position count and venue list are all unknown (source: command centre)."
            )

        if forge_tasks:
            forge_line = (
                f"• 🟠 **[FORGE]** `{forge_completed}` task(s) completed, `{forge_active}` in progress, "
                f"average test coverage `{avg_coverage:.1f}%` (source: forge manager)."
            )
        else:
            # `0` completed / `0.0%` coverage reads as a measurement of an idle
            # fleet. Nothing has been measured at all.
            forge_line = (
                "• 🟠 **[FORGE]** No tasks recorded, so there is no build count and no "
                "coverage figure to report (source: forge manager)."
            )

        feed_items = [trading_line, forge_line]
        if ai.get("available"):
            feed_items.append(
                f"• 🟢 **[AI-UNIVERSE]** Advisory systems reported {read_text(ai, 'status')} "
                "(source: command centre)."
            )
        else:
            feed_items.append(
                "• 🟢 **[AI-UNIVERSE]** No advisory status was reported by the command centre "
                "(source: command centre)."
            )
        feed_items.append(
            "• 🟣 **[FRIDAY]** Safety posture is derived from recorded incidents; a quiet feed here "
            "means no incident was recorded, not that none occurred."
        )

        bot_latency = read_number(bot, "api_latency_ms", source="trading bot")
        capital = read_number(bot, "active_capital_usdt", source="trading bot")
        positions = read_number(bot, "active_positions_count", source="trading bot")
        pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        leverage = read_number(risk, "aggregate_leverage", source="risk posture")
        proximity = read_number(risk, "daily_loss_limit_proximity_pct", source="risk posture")
        confidence = read_number(ai, "model_confidence", source="ai universe")
        venues = bot.get("connected_venues")
        venue_text = " / ".join(venues) if isinstance(venues, (list, tuple)) and venues else UNKNOWN_LABEL
        latest_delivery = (
            getattr(list(forge_tasks.values())[0], "delivery_package_path", None) if forge_tasks else None
        ) or "no delivery recorded"

        # FORGE is a local task manager here, not a probed service. The old
        # dashboard printed "**🟢 HEALTHY** (API: https://forge-e9kl.onrender.com
        # | HMAC-SHA256 Signed)" for it unconditionally - a green light, a URL
        # and a signing claim, none of which anything had checked.
        forge_status: dict[str, Any] = {
            "available": bool(forge_tasks),
            "status": "TASKS RECORDED" if forge_tasks else "NO TASKS RECORDED",
        }
        if self.forge_manager.demo_data:
            forge_status["status"] += " (SAMPLE DATA)"
            forge_status["note"] = "Sample tasks, not a live build. Remote FORGE service was not probed."

        headroom_text = (
            f"{100.0 - proximity.value:.1f}% remaining" if proximity.known else UNKNOWN_LABEL
        )

        def badge(reading: dict[str, Any]) -> str:
            if not reading.get("available"):
                return f"{_GREY} {UNKNOWN_LABEL}"
            text = str(reading.get("status", "UNKNOWN")).upper()
            light = _GREEN if text in {"HEALTHY", "OK", "ONLINE"} else _RED
            return f"{light} {text}"

        # ``risk.get('aggregate_leverage'):.2f`` raised "TypeError: unsupported
        # format string passed to NoneType.__format__" as soon as a value was
        # genuinely unknown, and everything else here was either a hardcoded
        # green light or a literal: the venue list was always "Binance Futures /
        # Bybit / OKX", P&L always carried a "+", and FORGE was announced
        # HEALTHY with no probe behind it at all.
        header = (
            f"# \U0001f310 FRIDAY Unified Ecosystem Master Dashboard\n\n"
            f"**Timestamp:** `{now_iso[:19]} UTC` | **Ecosystem State:** `{state}`\n"
            f"**Data provenance:** {status.get('data_provenance', 'unknown')}\n\n"
        )

        feed_section = "## \U0001f4e1 Cross-System Activity Feed\n" + "\n".join(feed_items) + "\n\n"

        builds_line = (
            f"`{forge_active}` in progress | `{forge_completed}` completed\n"
            if forge_tasks
            else "none recorded\n"
        )
        coverage_line = (
            f"`{avg_coverage:.1f}%` across {len(forge_tasks)} task(s)\n"
            if forge_tasks
            else "not measured - no task has been recorded, so there is no coverage number\n"
        )
        panels = (
            f"## \U0001f3db\ufe0f Tri-System Operational Panels\n\n"
            f"### \U0001f535 1. Algorithmic Trading Bot (`{venue_text}`)\n"
            f"- **Status:** {badge(bot)} (API Latency: `{bot_latency.number(1, ' ms')}`)\n"
            f"- **Capital Deployed:** `{capital.currency()} USDT` across `{positions.number(0)}` positions\n"
            f"- **Daily Realized P&L:** `{pnl.currency()} USDT`\n"
            f"- **Leverage:** `{leverage.number(2, 'x')}` | **Loss Headroom:** `{headroom_text}`\n\n"
            f"### \U0001f7e0 2. FORGE Software Engineering Engine\n"
            f"- **Status:** {badge(forge_status)}"
            f"{(' - ' + forge_status['note']) if forge_status.get('note') else ''}\n"
            f"- **Active Builds:** {builds_line}"
            f"- **Mean Test Coverage:** {coverage_line}"
            f"- **Latest Delivery:** `{latest_delivery}`\n\n"
            f"### \U0001f7e2 3. AI-Universe Trading Consultant & Analytics Core\n"
            f"- **Status:** {badge(ai)} (Model Confidence: `{confidence.percent(0)}`)\n"
            f"- **Multi-Agent Debate:** `{ai.get('debate_engine_status') or UNKNOWN_LABEL}`\n"
            f"- **Active Directional Forecasts:** `{read_number(ai, 'active_predictions_count').number(0)}` assets tracked\n\n"
        )

        controls = (
            "## \U0001f6a8 Emergency Master Controls\n"
            "- `\"Emergency stop trading\"` \u2192 Triggers instant kill-switch across all connected exchange venues\n"
            "- `\"Cancel FORGE task [id]\"` \u2192 Halts running autonomous build pipeline\n"
            "- `\"Set autonomy to level 1\"` \u2192 Switches ecosystem into non-executing SHADOW_MODE\n"
        )
        return header + feed_section + panels + controls
