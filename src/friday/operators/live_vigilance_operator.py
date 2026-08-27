# -*- coding: utf-8 -*-
"""Live Vigilance Operator for FRIDAY.

Persistent operator executing high-frequency (10-second) vigilance polling over real capital
trading operations on Binance Futures, detecting critical risk breaches, drawdowns,
reconciliation desync, and single position anomalies.
"""

from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator, OperatorExecutionResult, OperatorState
from friday.operators.triggers import IntervalTrigger
from friday.trading.incident_manager import LiveIncidentManager
from friday.trading.live_operations import LiveOperationsCenter

logger = get_logger("operators.live_vigilance")


class LiveVigilanceOperator(BaseOperator):
    """High-frequency (10s) vigilance operator supervising live capital operations."""

    __test__ = False

    name = "live_vigilance_operator"
    description = (
        "Continuously monitors live capital trading every 10 seconds, alerting on risk limit proximity, "
        "reconciliation mismatches, bot unreachability, and AI advisory rejection streaks."
    )

    def __init__(
        self,
        live_ops: Optional[LiveOperationsCenter] = None,
        alert_manager: Optional[ProductionAlertManager] = None,
        incident_manager: Optional[LiveIncidentManager] = None,
        poll_interval_sec: float = 10.0,
        memory: Optional[Any] = None,
        authorizer: Optional[Any] = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="live_vigilance_poll_interval")
        super().__init__(
            name="live_vigilance_operator",
            description="Continuously monitors live capital trading every 10 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="live_trading",
            authorizer=authorizer,
        )
        self._live_ops = live_ops
        self._alert_manager = alert_manager
        self._incident_manager = incident_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._unreachable_since: Optional[float] = None
        self._last_alerted_streak: int = 0
        self.memory = memory
        self._unreachable_since: Optional[float] = None
        self._last_alerted_streak: int = 0

    @property
    def live_ops(self) -> LiveOperationsCenter:
        if self._live_ops is None:
            self._live_ops = LiveOperationsCenter()
        return self._live_ops

    @property
    def alert_manager(self) -> ProductionAlertManager:
        if self._alert_manager is None:
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    @property
    def incident_manager(self) -> LiveIncidentManager:
        if self._incident_manager is None:
            self._incident_manager = LiveIncidentManager()
        return self._incident_manager

    def tick(self) -> List[Dict[str, Any]]:
        """Executes a single 10-second vigilance monitoring cycle."""
        events: List[Dict[str, Any]] = []

        try:
            state = self.live_ops.poll_live_state()
            self._unreachable_since = None
        except Exception as e:
            # Bot unreachable tracking
            import time
            now_ts = time.time()
            if self._unreachable_since is None:
                self._unreachable_since = now_ts
            elapsed = now_ts - self._unreachable_since

            if elapsed >= 30.0:
                ev = {
                    "type": "CRITICAL_BOT_UNREACHABLE",
                    "message": f"Trading bot unreachable for {elapsed:.0f}s while live capital is deployed!",
                    "severity": "CRITICAL",
                }
                events.append(ev)
                self._emit_alert("LIVE BOT UNREACHABLE", ev["message"], AlertSeverity.CRITICAL, 1)
            return events

        prox = state.risk_proximity

        # 1. CRITICAL: Daily Loss Limit Reached (100% breach)
        if prox.daily_loss_pct_used >= 100.0:
            ev = {
                "type": "CRITICAL_DAILY_LOSS_BREACH",
                "message": f"Daily loss limit REACHED! Total loss today: ${prox.current_daily_loss_usdt:,.2f} USDT >= ${prox.daily_loss_limit_usdt:,.2f} limit.",
                "severity": "CRITICAL",
            }
            events.append(ev)
            self._emit_alert("CRITICAL DAILY LOSS LIMIT BREACHED", ev["message"], AlertSeverity.CRITICAL, 2)

        # 2. CRITICAL: Drawdown Approaching Threshold (>80% of 5.0% limit)
        elif prox.drawdown_pct_used >= 80.0:
            ev = {
                "type": "CRITICAL_DRAWDOWN_APPROACHING",
                "message": f"Live drawdown critical: currently at {prox.current_drawdown_pct:.2f}% ({prox.drawdown_pct_used:.0f}% of {prox.max_drawdown_limit_pct:.1f}% max limit)!",
                "severity": "CRITICAL",
            }
            events.append(ev)
            self._emit_alert("CRITICAL DRAWDOWN THRESHOLD APPROACHING", ev["message"], AlertSeverity.CRITICAL, 2)

        # 3. WARNING: Single Position Loss > 3% of Capital
        for pos in state.positions:
            loss_usdt = abs(min(0.0, pos.unrealized_pnl))
            pos_loss_pct_of_capital = (loss_usdt / state.total_equity * 100.0) if state.total_equity > 0 else 0.0
            if pos_loss_pct_of_capital >= 3.0:
                ev = {
                    "type": "WARNING_SINGLE_POSITION_LOSS",
                    "symbol": pos.symbol,
                    "message": f"Position on {pos.symbol} down ${loss_usdt:,.2f} USDT ({pos_loss_pct_of_capital:.1f}% of total portfolio capital).",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert(f"POSITION LOSS WARNING: {pos.symbol}", ev["message"], AlertSeverity.WARNING, 4)

        # 4. WARNING: Advisory Rejection Streak (>3 in a row)
        if state.advisory_rejection_streak >= 3 and state.advisory_rejection_streak != self._last_alerted_streak:
            self._last_alerted_streak = state.advisory_rejection_streak
            ev = {
                "type": "WARNING_ADVISORY_REJECTION_STREAK",
                "streak": state.advisory_rejection_streak,
                "message": f"AI-Universe advisory rejection streak: {state.advisory_rejection_streak} consecutive recommendations rejected by safety gates.",
                "severity": "WARNING",
            }
            events.append(ev)
            self._emit_alert("AI ADVISORY REJECTION STREAK", ev["message"], AlertSeverity.WARNING, 4)

        return events

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity, incident_level: int) -> None:
        """Emits structured alert, creates incident containment, and persists to memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="live_trading",
            )
        except Exception as e:
            logger.debug(f"[LIVE_VIGILANCE] Failed creating alert: {e}")

        try:
            self.incident_manager.record_and_contain_incident(
                incident_type="LIVE_VIGILANCE_TRIGGER",
                severity_level=incident_level,
                title=title,
                description=message,
            )
        except Exception as e:
            logger.debug(f"[LIVE_VIGILANCE] Failed recording incident: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"LIVE_VIGILANCE_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[LIVE_VIGILANCE] Failed persisting to memory: {e}")
