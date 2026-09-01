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

        pnl_sign = "+" if state.total_pnl_today >= 0 else "-"

        # 1. Spoken Audio Briefing Text
        spoken = (
            f"Good morning Operator Surendra. Here is your live trading morning briefing for {datetime.now(timezone.utc).strftime('%A, %B %d')}. "
            f"Live operations are {state.trading_mode} on Capital Level {state.capital_level}. "
            f"Total account equity is ${state.total_equity:,.2f} USDT with today's P&L at {pnl_sign}${abs(state.total_pnl_today):,.2f} USDT across {len(state.positions)} open positions. "
            f"You have ${state.risk_proximity.daily_loss_headroom_usdt:,.2f} USDT in remaining daily risk budget with a drawdown of {state.risk_proximity.current_drawdown_pct:.2f}%. "
            f"Market regime analysis indicates {regime.primary_regime.value} with a recommended position sizing multiplier of {regime.position_sizing_multiplier}x. "
            f"Overnight AI-Universe activity recorded {state.advisory_applied_count} applied recommendations and {state.advisory_rejected_count} rejected by safety gates. "
            f"{'There are ' + str(len(active_incs)) + ' active incidents requiring review.' if active_incs else 'All safety gates and execution systems are fully normal.'}"
        )

        # 2. Markdown Visual Report
        pos_rows = []
        for p in state.positions:
            sign = "+" if p.unrealized_pnl >= 0 else "-"
            pos_rows.append(
                f"| **{p.symbol}** | `{p.side}` | `{p.size}` | `${p.entry_price:,.2f}` | `${p.mark_price:,.2f}` | **{sign}${abs(p.unrealized_pnl):,.2f} USDT** ({p.unrealized_pnl_pct:+.2f}%) |"
            )

        pos_table = (
            "| Symbol | Side | Size | Entry Price | Mark Price | Unrealized P&L |\n"
            "| :--- | :---: | :---: | :---: | :---: | :---: |\n" + "\n".join(pos_rows)
            if pos_rows else "*No open positions.*"
        )

        md = (
            f"# 🌅 FRIDAY Live Trading Morning Briefing\n\n"
            f"**Execution Mode:** `LIVE_BINANCE_FUTURES` | **Capital Tier:** `Level {state.capital_level}` | **Date:** `{now_iso[:10]}`\n\n"
            f"## 💰 Capital & Risk Telemetry\n"
            f"- **Account Equity:** **${state.total_equity:,.2f} USDT** (Cash: `${state.cash_balance:,.2f}`)\n"
            f"- **Today's Total P&L:** **{pnl_sign}${abs(state.total_pnl_today):,.2f} USDT** (Realized: `${state.realized_pnl_today:,.2f}`)\n"
            f"- **Remaining Daily Risk Budget:** **${state.risk_proximity.daily_loss_headroom_usdt:,.2f} USDT** ({state.risk_proximity.daily_loss_pct_used:.0f}% of limit used)\n"
            f"- **Current Drawdown:** **{state.risk_proximity.current_drawdown_pct:.2f}%** (Threshold: `{state.risk_proximity.max_drawdown_limit_pct:.1f}%`)\n\n"
            f"## 🌐 Market Regime Assessment\n"
            f"- **Primary Regime:** `{regime.primary_regime.value}` ({regime.timeframe_consensus})\n"
            f"- **Sizing Multiplier:** `{regime.position_sizing_multiplier}x` | **Risk Level:** `{regime.risk_level}`\n"
            f"- **Suitable Strategies:** {', '.join(f'`{s}`' for s in regime.suitable_strategies)}\n\n"
            f"## 📊 Active Live Positions\n{pos_table}\n\n"
            f"## 🤖 Overnight AI-Universe Telemetry\n"
            f"- **Applied Recommendations:** `{state.advisory_applied_count}`\n"
            f"- **Rejected by Safety Gates:** `{state.advisory_rejected_count}`\n"
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
