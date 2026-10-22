"""Live Operations Center for FRIDAY.

Provides continuous live trading supervision, real-time realized/unrealized P&L tracking,
risk limit proximity monitoring (daily loss limit, max drawdown), position monitoring,
and live AI advisory telemetry inspection.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("trading.live_operations")


@dataclass
class LivePosition:
    """Represents a live open market position."""
    symbol: str
    side: str  # LONG, SHORT
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    leverage: float
    liquidation_price: float


@dataclass
class RiskLimitProximity:
    """Proximity to hardcoded safety and daily loss limits."""
    daily_loss_limit_usdt: float
    #: ``None`` where the figure could not be computed because nothing was
    #: reported. The warning level is UNKNOWN rather than NORMAL in that case:
    #: "no evidence of risk" and "no evidence of anything" are different.
    current_daily_loss_usdt: float | None
    daily_loss_pct_used: float | None  # e.g., 70.0%
    daily_loss_headroom_usdt: float | None
    max_drawdown_limit_pct: float
    current_drawdown_pct: float | None
    drawdown_pct_used: float | None  # e.g., 30.0%
    max_positions_limit: int
    current_positions_count: int | None
    proximity_warning_level: str  # NORMAL, ELEVATED, CRITICAL, UNKNOWN


@dataclass
class LiveTradingState:
    """Comprehensive snapshot of live capital operations."""
    trading_mode: str  # LIVE, TESTNET, HALTED, PANIC, UNREPORTED
    #: ``None`` = the trading bridge did not report it. Never a placeholder: the
    #: briefing that speaks these used to print $10,540.25 / $8,200 / $310.50 /
    #: $140.25 and a BTC position nobody held.
    total_equity: float | None
    cash_balance: float | None
    realized_pnl_today: float | None
    unrealized_pnl: float | None
    total_pnl_today: float | None
    total_exposure_usdt: float | None
    effective_leverage: float | None
    positions: list[LivePosition]
    risk_proximity: RiskLimitProximity
    advisory_applied_count: int | None
    advisory_rejected_count: int | None
    advisory_rejection_streak: int | None
    #: ``None`` when no capital tier was configured or reported.
    capital_level: int | None
    #: False when the trading bot reported nothing at all.
    available: bool = True
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        def _round(value, digits: int = 2):
            return round(value, digits) if isinstance(value, (int, float)) else None

        return {
            "available": self.available,
            "trading_mode": self.trading_mode,
            "total_equity": _round(self.total_equity),
            "cash_balance": _round(self.cash_balance),
            "realized_pnl_today": _round(self.realized_pnl_today),
            "unrealized_pnl": _round(self.unrealized_pnl),
            "total_pnl_today": _round(self.total_pnl_today),
            "total_exposure_usdt": _round(self.total_exposure_usdt),
            "effective_leverage": _round(self.effective_leverage),
            "positions": [p.__dict__ for p in self.positions],
            "risk_proximity": self.risk_proximity.__dict__,
            "advisory_applied_count": self.advisory_applied_count,
            "advisory_rejected_count": self.advisory_rejected_count,
            "advisory_rejection_streak": self.advisory_rejection_streak,
            "capital_level": self.capital_level,
            "timestamp": self.timestamp,
        }


class LiveOperationsCenter:
    """Central engine supervising real capital deployment on Binance Futures."""

    def __init__(
        self,
        bot_operator: Any | None = None,
        daily_loss_limit_usdt: float = 500.0,
        max_drawdown_limit_pct: float = 5.0,
        max_positions: int = 5,
        capital_level: int | None = None,
    ) -> None:
        self._bot_operator = bot_operator
        self.daily_loss_limit_usdt = daily_loss_limit_usdt
        self.max_drawdown_limit_pct = max_drawdown_limit_pct
        self.max_positions = max_positions
        #: Capital tier. ``None`` unless configured or reported by the bridge:
        #: this used to be the literal 1, announced as "Capital Level 1" in the
        #: morning briefing regardless of the account.
        self.capital_level = capital_level
        self._lock = threading.RLock()
        self._last_state: LiveTradingState | None = None

    @property
    def bot_operator(self) -> Any:
        if self._bot_operator is None:
            from friday.skills.trading_bot_operator import TradingBotOperator
            self._bot_operator = TradingBotOperator()
        return self._bot_operator

    def poll_live_state(self) -> LiveTradingState:
        """Polls live trading telemetry and computes risk proximity metrics."""
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            status_data = self.bot_operator.get_status()
        except Exception as e:
            logger.error(f"[LIVE_OPS] Failed fetching live bot status: {e}")
            status_data = {}

        # Nothing below substitutes a value the bridge did not send. The old
        # version defaulted to mode "LIVE", equity 10540.25, cash 8200.0,
        # realised 310.50, unrealised 140.25, drawdown 1.45% and - when no
        # positions came back - a long 0.05 BTC position at 64,000 with 25.0
        # unrealised P&L and an exposure of 3225.0. The morning briefing then
        # read those aloud as the operator's live account.
        reported = bool(status_data)

        def _num(*keys, default=None):
            for key in keys:
                value = status_data.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return default

        mode = str(status_data.get("trading_mode") or status_data.get("mode") or "UNREPORTED").upper()
        equity = _num("equity", "current_equity", "total_equity")
        cash = _num("cash", "cash_balance")
        realized = _num("realized_pnl", "realized_pnl_today")
        unrealized = _num("unrealized_pnl")
        total_pnl = (realized + unrealized) if (realized is not None and unrealized is not None) else None

        # Parse live positions - only the ones that were actually reported.
        raw_positions = status_data.get("positions", status_data.get("active_positions", []))
        if isinstance(raw_positions, dict):
            raw_positions = list(raw_positions.values())
        if not isinstance(raw_positions, list):
            raw_positions = []

        positions: list[LivePosition] = []
        total_exposure = 0.0

        for p in raw_positions:
            if not isinstance(p, dict):
                continue
            size = abs(float(p.get("size", 0.0) or 0.0))
            entry = float(p.get("entry_price") or p.get("mark_price") or 0.0)
            mark = float(p.get("mark_price") or entry)
            u_pnl = float(p.get("unrealized_pnl") or 0.0)
            u_pct = (u_pnl / (size * entry) * 100.0) if (size * entry) > 0 else 0.0

            total_exposure += size * mark
            positions.append(
                LivePosition(
                    symbol=str(p.get("symbol") or "unspecified"),
                    side=str(p.get("side") or "unspecified").upper(),
                    size=size,
                    entry_price=entry,
                    mark_price=mark,
                    unrealized_pnl=u_pnl,
                    unrealized_pnl_pct=u_pct,
                    leverage=float(p.get("leverage") or 0.0),
                    liquidation_price=float(p.get("liquidation_price") or 0.0),
                )
            )

        total_exposure_value: float | None = total_exposure if reported else None
        eff_leverage = (
            (total_exposure_value / equity) if (total_exposure_value is not None and equity) else None
        )

        # Risk proximity - each figure computed only from reported inputs, and
        # warning level UNKNOWN when there was nothing to compute from.
        loss_today = abs(min(0.0, total_pnl)) if total_pnl is not None else None
        daily_loss_pct_used = (
            (loss_today / self.daily_loss_limit_usdt * 100.0)
            if (loss_today is not None and self.daily_loss_limit_usdt > 0)
            else None
        )
        daily_headroom = (
            max(0.0, self.daily_loss_limit_usdt - loss_today) if loss_today is not None else None
        )

        current_dd_pct = _num("drawdown_pct", "current_drawdown_pct")
        dd_pct_used = (
            (current_dd_pct / self.max_drawdown_limit_pct * 100.0)
            if (current_dd_pct is not None and self.max_drawdown_limit_pct > 0)
            else None
        )

        if daily_loss_pct_used is None and dd_pct_used is None:
            warning_level = "UNKNOWN"
        elif (daily_loss_pct_used or 0.0) >= 80.0 or (dd_pct_used or 0.0) >= 80.0:
            warning_level = "CRITICAL"
        elif (daily_loss_pct_used or 0.0) >= 50.0 or (dd_pct_used or 0.0) >= 50.0:
            warning_level = "ELEVATED"
        else:
            warning_level = "NORMAL"

        proximity = RiskLimitProximity(
            daily_loss_limit_usdt=self.daily_loss_limit_usdt,
            current_daily_loss_usdt=round(loss_today, 2) if loss_today is not None else None,
            daily_loss_pct_used=round(daily_loss_pct_used, 1) if daily_loss_pct_used is not None else None,
            daily_loss_headroom_usdt=round(daily_headroom, 2) if daily_headroom is not None else None,
            max_drawdown_limit_pct=self.max_drawdown_limit_pct,
            current_drawdown_pct=round(current_dd_pct, 2) if current_dd_pct is not None else None,
            drawdown_pct_used=round(dd_pct_used, 1) if dd_pct_used is not None else None,
            max_positions_limit=self.max_positions,
            current_positions_count=len(positions) if reported else None,
            proximity_warning_level=warning_level,
        )

        # AI Advisory stats. The exception handler used to report "4 applied, 1
        # rejected" - an advisory log invented at the moment the real one could
        # not be read.
        applied: int | None = None
        rejected: int | None = None
        streak: int | None = None
        try:
            adv_recent = self.bot_operator.get_advisory_recent(limit=10)
            logs = adv_recent.get("advisory_log", adv_recent.get("logs", [])) or []
            applied = sum(1 for a in logs if str(a.get("bot_verdict", a.get("verdict", ""))).upper() == "APPLY")
            rejected = sum(1 for a in logs if str(a.get("bot_verdict", a.get("verdict", ""))).upper() == "REJECT")
            streak = 0
            for a in logs:
                if str(a.get("bot_verdict", a.get("verdict", ""))).upper() == "REJECT":
                    streak += 1
                else:
                    break
        except Exception as exc:
            logger.warning("[LIVE_OPS] Advisory log unavailable: %s", exc)

        state = LiveTradingState(
            trading_mode=mode,
            total_equity=equity,
            cash_balance=cash,
            realized_pnl_today=realized,
            unrealized_pnl=unrealized,
            total_pnl_today=total_pnl,
            total_exposure_usdt=total_exposure_value,
            effective_leverage=eff_leverage,
            positions=positions,
            risk_proximity=proximity,
            advisory_applied_count=applied,
            advisory_rejected_count=rejected,
            advisory_rejection_streak=streak,
            capital_level=(
                int(status_data["capital_level"])
                if isinstance(status_data.get("capital_level"), (int, float))
                else self.capital_level
            ),
            available=reported,
        )

        with self._lock:
            self._last_state = state

        return state

    def get_spoken_pnl_summary(self) -> str:
        """Returns concise spoken P&L report, or says nothing was reported."""
        from friday.core.readings import format_money

        state = self.poll_live_state()
        if not state.available:
            return (
                "The trading bridge has not reported, so I have no P&L, no position list and no "
                "equity figure to read to you. I will not quote numbers I do not have."
            )
        return (
            f"Reported live P&L today is {format_money(state.total_pnl_today)} USDT. "
            f"Realized is {format_money(state.realized_pnl_today)} USDT with an unrealized balance of "
            f"{format_money(state.unrealized_pnl)} USDT across {len(state.positions)} open positions. "
            f"Total live equity is {format_money(state.total_equity)} USDT."
        )

    def get_spoken_risk_proximity_summary(self) -> str:
        """Returns spoken summary of distance to risk limits."""
        from friday.core.readings import format_money, format_number

        state = self.poll_live_state()
        prox = state.risk_proximity

        if prox.proximity_warning_level == "UNKNOWN":
            return (
                "I cannot report risk proximity: the trading bridge has reported neither a P&L nor a "
                "drawdown figure, so there is no basis for telling you how close you are to a limit. "
                f"Risk proximity rating is UNKNOWN, not NORMAL. (Daily loss limit configured: "
                f"{format_money(prox.daily_loss_limit_usdt)} USDT; max drawdown "
                f"{format_number(prox.max_drawdown_limit_pct, 1, '%')}.)"
            )
        return (
            f"Risk limit status: You are currently at {format_number(prox.daily_loss_pct_used, 0, '%')} of your "
            f"daily loss limit, with {format_money(prox.daily_loss_headroom_usdt)} USDT in risk headroom "
            f"remaining today. Current drawdown is {format_number(prox.current_drawdown_pct, 2, '%')}, which "
            f"is {format_number(prox.drawdown_pct_used, 0, '%')} of the "
            f"{format_number(prox.max_drawdown_limit_pct, 1, '%')} maximum threshold. "
            f"Risk proximity rating is {prox.proximity_warning_level}."
        )
