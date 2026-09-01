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

        # Status Badges
        bot_badge = "🟢 ONLINE" if bot.get("status") in ("ACTIVE", "HEALTHY") else ("🔴 PANIC" if bot.get("status") == "PANIC" else "⚠️ DOWN")
        ai_badge = "🟢 HEALTHY" if ai.get("health") == "HEALTHY" else "⚠️ DEGRADED"
        sys_badge = "🟢 HEALTHY" if report.overall_status == "HEALTHY" else ("⚠️ DEGRADED" if report.overall_status == "DEGRADED" else "🚨 CRITICAL")

        # Metric parsing
        equity = float(bot.get("equity", 10000.0))
        cash = float(bot.get("cash", 8000.0))
        unrealized = float(bot.get("unrealized_pnl", 0.0))
        today_pnl = float(bot.get("today_pnl", 0.0))
        pf = float(bot.get("profit_factor", 1.5))
        win_rate = float(bot.get("win_rate_pct", 55.0))
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
            alert_table = "✅ *No active unacknowledged alerts. All systems running within normal parameters.*"

        # Positions table
        pos_rows = []
        if positions:
            for p in positions:
                sym = p.get("symbol", "UNKNOWN")
                side = p.get("side", "LONG")
                size = p.get("size", 0.0)
                pnl = p.get("unrealized_pnl", 0.0)
                pos_rows.append(f"| **{sym}** | `{side}` | {size} | {pnl:+.2f} USDT |")
            pos_table = (
                "| Symbol | Side | Size | Unrealized PnL |\n"
                "| :--- | :---: | :---: | :---: |\n" + "\n".join(pos_rows)
            )
        else:
            pos_table = "*No active open positions.*"

        # Cascading failure alert
        cascade_block = ""
        if report.cascading_failures:
            cascade_block = "\n> 🚨 **CASCADING FAILURE DETECTED:**\n" + "\n".join(f"> - {f}" for f in report.cascading_failures) + "\n"

        dashboard_md = (
            f"# 🎛️ FRIDAY Production Supervision Dashboard\n\n"
            f"**Overall Health:** **{sys_badge}** | **Environment:** `BINANCE_FUTURES_TESTNET` | **Updated:** `{report.timestamp[:19]} UTC`\n"
            f"{cascade_block}\n"
            f"## 🏛️ System Tier Status Overview\n\n"
            f"| Tier Component | Status | Latency | Key Details |\n"
            f"| :--- | :---: | :---: | :--- |\n"
            f"| **Trading Bot Engine** | **{bot_badge}** | `{bot.get('latency_ms', 0)}ms` | Mode: `{bot.get('trading_mode', 'TESTNET')}`, Status: `{bot.get('status', 'ACTIVE')}` |\n"
            f"| **AI-Universe Intelligence** | **{ai_badge}** | `{ai.get('latency_ms', 0)}ms` | Enabled: `{ai.get('enabled', True)}`, Last Consult: `{ai.get('last_consult', 'Recent')}` |\n"
            f"| **FRIDAY Operating System** | **🟢 HEALTHY** | `<1ms` | Threads: `{report.friday_os.get('active_threads')}`, PID: `{report.friday_os.get('pid')}` |\n\n"
            f"## 📈 Trading Performance Summary\n\n"
            f"- **Account Equity:** **${equity:,.2f} USDT** (Cash: `${cash:,.2f}`)\n"
            f"- **Today's Cumulative PnL:** **{today_pnl:+.2f} USDT** (Unrealized: `{unrealized:+.2f} USDT`)\n"
            f"- **Profit Factor:** **{pf:.2f}** | **Win Rate:** **{win_rate:.1f}%**\n"
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
            bot = self.bot_operator.get_status()
            equity = float(bot.get("equity", 10000.0))
            unrealized = float(bot.get("unrealized_pnl", 0.0))
            today_pnl = float(bot.get("today_pnl", 0.0))
            pf = float(bot.get("profit_factor", 1.5))
            win_rate = float(bot.get("win_rate_pct", 55.0))
            pos_count = len(bot.get("positions", []))

            return (
                f"Trading performance is active on Binance Futures Testnet. Total equity is ${equity:,.2f} USDT "
                f"with an unrealized PnL of {unrealized:+.2f} USDT across {pos_count} open positions. "
                f"Today's cumulative return is {today_pnl:+.2f} USDT with a profit factor of {pf:.2f} and a win rate of {win_rate:.1f}%."
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
