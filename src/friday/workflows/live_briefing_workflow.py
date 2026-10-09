"""Live Morning Briefing Workflow for FRIDAY.

Generates comprehensive morning live operations briefings:
- Overnight performance & open live positions
- Risk limit proximity & remaining daily risk budget
- Market regime analysis & recommended strategy posture
- Overnight AI advisory activity & applied parameter overlays
- Active incidents and alert clearances
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.trading.live_operations import LiveOperationsCenter
from friday.trading.regime_detector import MarketRegimeDetector

logger = get_logger("workflows.live_briefing")


@dataclass
class LiveBriefingSnapshot:
    """Snapshot containing all live morning briefing telemetry."""
    timestamp: str
    trading_mode: str
    capital_level: int
    total_equity: float
    total_pnl_today: float
    open_positions_count: int
    daily_loss_headroom_usdt: float
    drawdown_pct: float
    primary_regime: str
    regime_consensus: str
    position_sizing_multiplier: float
    advisory_applied: int
    advisory_rejected: int
    active_incidents_count: int
    spoken_briefing: str
    markdown_report: str


class LiveMorningBriefingWorkflow:
    """Assembles and delivers real-time morning briefings for live trading operations."""

    def __init__(
        self,
        live_ops: LiveOperationsCenter | None = None,
        regime_detector: MarketRegimeDetector | None = None,
        incident_manager: Any | None = None,
    ) -> None:
        self._live_ops = live_ops
        self._regime_detector = regime_detector
        self._incident_manager = incident_manager

    @property
    def live_ops(self) -> LiveOperationsCenter:
        if self._live_ops is None:
            self._live_ops = LiveOperationsCenter()
        return self._live_ops

    @property
    def regime_detector(self) -> MarketRegimeDetector:
        if self._regime_detector is None:
            self._regime_detector = MarketRegimeDetector()
        return self._regime_detector

    @property
    def incident_manager(self) -> Any:
        if self._incident_manager is None:
            from friday.trading.incident_manager import LiveIncidentManager
            self._incident_manager = LiveIncidentManager()
        return self._incident_manager

    def can_handle(self, user_request: str) -> bool:
        """Determines if the request is for a live morning briefing."""
        clean = user_request.strip().lower()
        return any(k in clean for k in ["live morning briefing", "live briefing", "morning live report"])

    def generate_briefing(self) -> LiveBriefingSnapshot:
        """Generates unified live morning briefing snapshot."""
        now_iso = datetime.now(timezone.utc).isoformat()
        state = self.live_ops.poll_live_state()
        regime = self.regime_detector.detect_regime()
        active_incs = self.incident_manager.get_active_incidents()

        from friday.core.readings import format_money, format_number

        # Every clause below used to read a default out of the polled state as
        # though it were telemetry: "Live operations are LIVE", "$10,540.25 equity
        # with today's P&L at +$450.75 across 1 open positions", "$500.00 in
        # remaining daily risk budget", a drawdown of 1.45%, "4 applied
        # recommendations and 1 rejected", and a market regime from three invented
        # indicators. The numbers are now what the bridge reported, or named as
        # unreported.
        def _money(value) -> str:
            return format_money(value)

        def _count(value) -> str:
            return str(value) if isinstance(value, int) else "an unreported number of"

        if not state.available:
            spoken = (
                f"Good morning Operator Surendra. This is your live trading briefing for "
                f"{datetime.now(timezone.utc).strftime('%A, %B %d')}. The trading bridge has not "
                f"reported, so I have no equity, no P&L, no positions and no risk proximity to give "
                f"you. I am not going to read you figures that nothing produced."
            )
            md = (
                f"# 🌅 FRIDAY Live Trading Morning Briefing\n\n"
                f"**Generated:** `{now_iso[:19]} UTC`\n\n"
                f"**The trading bridge has reported nothing.** Equity, P&L, positions, risk proximity "
                f"and advisory activity are all unknown; this briefing does not fill them in.\n"
            )
        else:
            spoken = (
                f"Good morning Operator Surendra. Here is your live trading morning briefing for {datetime.now(timezone.utc).strftime('%A, %B %d')}. "
                f"Reported trading mode is {state.trading_mode}. "
                f"Reported equity is {_money(state.total_equity)} USDT with today's P&L at {_money(state.total_pnl_today)} USDT "
                f"across {len(state.positions)} reported position(s). "
                f"Remaining daily risk budget is {_money(state.risk_proximity.daily_loss_headroom_usdt)} USDT with a "
                f"drawdown of {format_number(state.risk_proximity.current_drawdown_pct, 2, '%')}. "
                f"Reported AI-Universe activity: {_count(state.advisory_applied_count)} applied recommendations and "
                f"{_count(state.advisory_rejected_count)} rejected by safety gates. "
                f"Risk proximity rating is {state.risk_proximity.proximity_warning_level}."
            )

        if state.available:
            # 2. Markdown Visual Report
            md = (
                f"# 🌅 FRIDAY Live Trading Morning Briefing\n\n"
                f"**Generated:** `{now_iso[:19]} UTC` | **Trading Mode:** `{state.trading_mode}` | "
                f"**Data provenance:** reported by the trading bridge; unreported values are named.\n\n"
                f"## 📈 Account\n"
                f"- **Equity:** `{_money(state.total_equity)} USDT` (Cash: `{_money(state.cash_balance)}`)\n"
                f"- **Today's P&L:** `{_money(state.total_pnl_today)} USDT` "
                f"(Realized `{_money(state.realized_pnl_today)}` / Unrealized `{_money(state.unrealized_pnl)}`)\n"
                f"- **Reported Positions:** `{len(state.positions)}`\n\n"
                f"## ⚠️ Risk Proximity (`{state.risk_proximity.proximity_warning_level}`)\n"
                f"- **Daily Loss Used:** `{format_number(state.risk_proximity.daily_loss_pct_used, 1, '%')}` of "
                f"`{_money(state.risk_proximity.daily_loss_limit_usdt)} USDT`\n"
                f"- **Headroom:** `{_money(state.risk_proximity.daily_loss_headroom_usdt)} USDT`\n"
                f"- **Drawdown:** `{format_number(state.risk_proximity.current_drawdown_pct, 2, '%')}`\n"
            )

        # 2. Markdown Visual Report (only when the bridge reported something).
        if state.available:
            pos_rows = []
            for p in state.positions:
                pos_rows.append(
                    f"| **{p.symbol}** | `{p.side}` | `{p.size}` | `${p.entry_price:,.2f}` | "
                    f"`${p.mark_price:,.2f}` | ${p.unrealized_pnl:,.2f} USDT ({p.unrealized_pnl_pct:+.2f}%) |"
                )

            pos_table = (
                "| Symbol | Side | Size | Entry Price | Mark Price | Unrealized P&L |\n"
                "| :--- | :---: | :---: | :---: | :---: | :---: |\n" + "\n".join(pos_rows)
                if pos_rows else "*No position was reported open.*"
            )

            regime_block = (
                f"- **Primary Regime:** `{regime.primary_regime.value}` ({regime.timeframe_consensus})\n"
                f"- **Sizing Multiplier:** `{format_number(regime.position_sizing_multiplier, 2, 'x')}` | "
                f"**Risk Level:** `{regime.risk_level}`\n"
                f"- **Suitable Strategies:** {', '.join(f'`{s}`' for s in regime.suitable_strategies)}\n"
                if regime.available
                else "- **Primary Regime:** unknown (no ADX/BBW/ATR reading was supplied; the detector "
                "does not infer them)\n"
            )

            md += (
                f"**Execution Mode:** `{state.trading_mode}` | "
                f"**Capital Tier:** `{'Level ' + str(state.capital_level) if state.capital_level is not None else 'not reported'}` | "
                f"**Date:** `{now_iso[:10]}`\n\n"
                f"## 💰 Capital & Risk Telemetry\n"
                f"- **Account Equity:** **{_money(state.total_equity)} USDT** (Cash: `{_money(state.cash_balance)}`)\n"
                f"- **Today's Total P&L:** **{_money(state.total_pnl_today)} USDT** "
                f"(Realized: `{_money(state.realized_pnl_today)}`, Unrealized: `{_money(state.unrealized_pnl)}`)\n"
                f"- **Remaining Daily Risk Budget:** "
                f"**{_money(state.risk_proximity.daily_loss_headroom_usdt)} USDT** "
                f"(`{format_number(state.risk_proximity.daily_loss_pct_used, 0, '%')}` of limit used)\n"
                f"- **Current Drawdown:** **{format_number(state.risk_proximity.current_drawdown_pct, 2, '%')}** "
                f"(Threshold: `{format_number(state.risk_proximity.max_drawdown_limit_pct, 1, '%')}`)\n\n"
                f"## 🌐 Market Regime Assessment\n"
                f"{regime_block}\n"
                f"## 📊 Reported Live Positions\n{pos_table}\n\n"
                f"## 🤖 Overnight AI-Universe Telemetry\n"
                f"- **Applied Recommendations:** `{_count(state.advisory_applied_count)}`\n"
                f"- **Rejected by Safety Gates:** `{_count(state.advisory_rejected_count)}`\n"
                f"- **Active Incidents:** `{len(active_incs)}`\n"
            )

        return LiveBriefingSnapshot(
            timestamp=now_iso,
            trading_mode=state.trading_mode,
            capital_level=state.capital_level,
            total_equity=state.total_equity,
            total_pnl_today=state.total_pnl_today,
            open_positions_count=len(state.positions),
            daily_loss_headroom_usdt=state.risk_proximity.daily_loss_headroom_usdt,
            drawdown_pct=state.risk_proximity.current_drawdown_pct,
            primary_regime=regime.primary_regime.value,
            regime_consensus=regime.timeframe_consensus,
            position_sizing_multiplier=regime.position_sizing_multiplier,
            advisory_applied=state.advisory_applied_count,
            advisory_rejected=state.advisory_rejected_count,
            active_incidents_count=len(active_incs),
            spoken_briefing=spoken,
            markdown_report=md,
        )
