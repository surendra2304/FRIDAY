"""Production Supervision Dashboard for FRIDAY.

Generates real-time visual summaries, metric comparisons, alert tables,
and status dashboards across the Trading Bot, AI-Universe, and FRIDAY OS tiers.
"""

from typing import Any


class ProductionDashboard:
    """Renders comprehensive production supervision views and metrics."""

    def __init__(
        self,
        bot_operator: Any | None = None,
        alert_manager: Any | None = None,
        emergency_manager: Any | None = None,
        production_monitor: Any | None = None,
    ) -> None:
        if bot_operator is None:
            from friday.skills.trading_bot_operator import TradingBotOperator
            bot_operator = TradingBotOperator()
        if alert_manager is None:
            from friday.alert_manager import ProductionAlertManager
            alert_manager = ProductionAlertManager()
        if emergency_manager is None:
            from friday.emergency_procedures import EmergencyProcedureManager
            emergency_manager = EmergencyProcedureManager(bot_operator=bot_operator, alert_manager=alert_manager)
        if production_monitor is None:
            from friday.production_monitor import ProductionMonitor
            production_monitor = ProductionMonitor(
                bot_operator=bot_operator, alert_manager=alert_manager
            )

        self.bot_operator = bot_operator
        self.alert_manager = alert_manager
        self.emergency_manager = emergency_manager
        self.production_monitor = production_monitor

    def render_markdown_dashboard(self) -> str:
        """Renders the full multi-tier production supervision dashboard in Markdown."""
        report = self.production_monitor.poll_all_systems()
        bot = report.trading_bot
        ai = report.ai_universe
        active_alerts = self.alert_manager.get_active_alerts()

        # Status Badges. Green is reserved for a reported healthy state; an
        # unreported subsystem used to be badged "⚠️ DEGRADED" (a judgement) and
        # the FRIDAY OS row below was hardcoded "🟢 HEALTHY".
        def _badge(value: str | None) -> str:
            text = str(value or "UNREPORTED").upper()
            if text in ("ONLINE", "ACTIVE", "HEALTHY", "OK"):
                return f"🟢 {text}"
            if text in ("UNREPORTED", "UNKNOWN", ""):
                return "⚪ UNREPORTED"
            return f"🔴 {text}" if text in ("DOWN", "PANIC", "UNREACHABLE") else f"⚠️ {text}"

        bot_badge = _badge(bot.get("status"))
        ai_badge = _badge(ai.get("health"))
        sys_badge = {
            "HEALTHY": "🟢 HEALTHY",
            "DEGRADED": "⚠️ DEGRADED",
            "UNVERIFIED": "⚪ UNVERIFIED",
            "CRITICAL": "🚨 CRITICAL",
        }.get(report.overall_status, f"⚪ {report.overall_status}")

        # Metric parsing. A missing figure is None and renders as unknown: the
        # defaults here were $10,000 equity, $8,000 cash, a 1.5 profit factor and
        # a 55% win rate, all printed as the operator's account.
        from friday.core.readings import format_money, format_number

        def _num(key: str):
            value = bot.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        equity = _num("equity")
        cash = _num("cash")
        unrealized = _num("unrealized_pnl")
        today_pnl = _num("today_pnl")
        pf = _num("profit_factor")
        win_rate = _num("win_rate_pct")
        positions = bot.get("positions", [])

        # Active Parameter Overlays
        overlays = ai.get("active_overlay", {})
        overlay_str = ", ".join(f"`{k}`: {v}" for k, v in overlays.items()) if overlays else "None (Baseline defaults)"

        # Alert table
        alert_rows = []
        if active_alerts:
            for a in active_alerts[:5]:
                alert_rows.append(f"| `{a.id}` | `{a.severity.value}` | **{a.title}** | {a.message} | `{a.created_at[:19]}` |")
            alert_table = (
                "| Alert ID | Severity | Title | Summary | Timestamp |\n"
                "| :--- | :---: | :--- | :--- | :--- |\n" + "\n".join(alert_rows)
            )
        else:
            alert_table = (
                "*No unacknowledged alert is on record. That is not evidence that every limit was "
                "measured - only that nothing was raised.*"
            )

        # Positions table
        pos_rows = []
        if positions:
            for p in positions:
                sym = p.get("symbol") or "unspecified"
                side = p.get("side") or "unspecified"
                size = p.get("size", "not reported")
                pnl = p.get("unrealized_pnl", 0.0)
                pos_rows.append(f"| **{sym}** | `{side}` | {size} | {pnl:+.2f} USDT |")
            pos_table = (
                "| Symbol | Side | Size | Unrealized PnL |\n"
                "| :--- | :---: | :---: | :---: |\n" + "\n".join(pos_rows)
            )
        else:
            pos_table = "*No position was reported by the trading bridge.*"

        # Cascading failure alert
        cascade_block = ""
        if report.cascading_failures:
            cascade_block = "\n> 🚨 **CASCADING FAILURE DETECTED:**\n" + "\n".join(f"> - {f}" for f in report.cascading_failures) + "\n"

        dashboard_md = (
            f"# 🎛️ FRIDAY Production Supervision Dashboard\n\n"
            f"**Overall Health:** **{sys_badge}** | **Environment Reported:** "
            f"`{bot.get('trading_mode') or 'not reported'}` | **Updated:** `{report.timestamp[:19]} UTC`\n"
            f"{cascade_block}\n"
            f"## 🏛️ System Tier Status Overview\n\n"
            f"| Tier Component | Status | Latency | Key Details |\n"
            f"| :--- | :---: | :---: | :--- |\n"
            f"| **Trading Bot Engine** | **{bot_badge}** | `{format_number(bot.get('latency_ms'), 0, ' ms')}` | "
            f"Mode: `{bot.get('trading_mode') or 'not reported'}`, Reported: `{bot.get('error') or 'ok'}` |\n"
            f"| **AI-Universe Intelligence** | **{ai_badge}** | `{format_number(ai.get('latency_ms'), 0, ' ms')}` | "
            f"Enabled: `{ai.get('enabled', 'not reported')}`, Last Consult: `{ai.get('last_consult') or 'not reported'}` |\n"
            f"| **FRIDAY Operating System** | **⚪ SELF-REPORT** | `n/a` | "
            f"Threads: `{report.friday_os.get('active_threads')}`, PID: `{report.friday_os.get('pid')}` |\n\n"
            f"## 📈 Trading Performance Summary\n\n"
            f"- **Account Equity:** **{format_money(equity)} USDT** (Cash: `{format_money(cash)}`)\n"
            f"- **Today's Cumulative PnL:** **{format_money(today_pnl)} USDT** "
            f"(Unrealized: `{format_money(unrealized)} USDT`)\n"
            f"- **Profit Factor:** **{format_number(pf, 2)}** | **Win Rate:** **{format_number(win_rate, 1, '%')}**\n"
            f"- **AI Parameter Overlays:** {overlay_str}\n\n"
            f"### Active Positions\n{pos_table}\n\n"
            f"## 🚨 Active Alerts & Incidents\n{alert_table}\n\n"
            f"## 🛑 Emergency Controls Quick Actions\n"
            f"- **Emergency Trading Halt:** Say *'Emergency halt'* to invoke the trading bot kill-switch (`POST /api/panic`).\n"
            f"- **Rollback Parameters:** Say *'Rollback parameters'* to revert AI overlays to baseline safe defaults.\n"
            f"- **Acknowledge Alert:** Say *'Acknowledge alert [ID]'* to register operator response.\n"
        )
        return dashboard_md

    def render_trading_performance_summary(self) -> str:
        """Returns a spoken and concise performance summary."""
        try:
            from friday.core.readings import format_money, format_number

            bot = self.bot_operator.get_status()

            def _num(key: str):
                value = bot.get(key)
                return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

            if not bot:
                return (
                    "The trading bridge has not reported, so I have no equity, P&L, profit factor or "
                    "win rate to summarise."
                )

            pos_count = len(bot.get("positions", []) or [])
            return (
                f"Reported trading mode is {bot.get('trading_mode') or 'not reported'}. Total equity is "
                f"{format_money(_num('equity'))} USDT with an unrealized PnL of "
                f"{format_money(_num('unrealized_pnl'))} USDT across {pos_count} reported positions. "
                f"Today's return is {format_money(_num('today_pnl'))} USDT with a profit factor of "
                f"{format_number(_num('profit_factor'), 2)} and a win rate of "
                f"{format_number(_num('win_rate_pct'), 1, '%')}."
            )
        except Exception as e:
            return f"Failed to retrieve trading performance: {e}"

    def render_ai_advisory_status(self) -> str:
        """Returns spoken summary of AI advisory health and recent decisions."""
        try:
            return self.bot_operator.get_advisory_summary()
        except Exception as e:
            return f"Failed to retrieve AI advisory status: {e}"

    def render_alerts_summary(self) -> str:
        """Returns summary of active alerts."""
        active = self.alert_manager.get_active_alerts()
        if not active:
            return "There are currently no active alerts. All systems are operating normally."

        lines = [f"There are {len(active)} active alerts requiring attention:"]
        for a in active[:5]:
            lines.append(f"• Alert `{a.id}` [{a.severity.value}]: {a.title} - {a.message}")
        return "\n".join(lines)
