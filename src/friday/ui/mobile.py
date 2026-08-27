# -*- coding: utf-8 -*-
"""Mobile Dashboard Interface for FRIDAY Operating System.

Responsive single-column interface tailored for mobile companions:
1. Single-column card layout with touch-optimized controls
2. Bottom tab navigation: Home, Trading, Forge, Nexus, Alerts
3. Double-tap emergency action protection (panic / halt within 3s)
4. Offline cache sync indicator and state management
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ui.mobile")


@dataclass
class MobileViewData:
    """Mobile dashboard view state."""
    active_tab: str  # home, trading, forge, nexus, alerts
    is_offline: bool
    last_synced_at: str
    cards: List[Dict[str, Any]] = field(default_factory=list)
    pending_emergency_action: Optional[str] = None


class MobileDashboardInterface:
    """Renders and manages mobile companion interactions."""

    TABS = ["home", "trading", "forge", "nexus", "alerts"]

    def __init__(self) -> None:
        self._active_tab = "home"
        self._cached_state: Dict[str, Any] = {
            "trading_equity": 10450.0,
            "active_positions": 2,
            "forge_active_tasks": 1,
            "nexus_leads_today": 8,
            "recent_alerts": ["Supertrend ATR stop loss updated"],
        }
        self._last_sync = datetime.now(timezone.utc)
        self._pending_double_tap: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()

    def set_tab(self, tab_name: str) -> bool:
        """Switches active bottom navigation tab."""
        with self._lock:
            clean = tab_name.strip().lower()
            if clean in self.TABS:
                self._active_tab = clean
                return True
            return False

    def handle_emergency_tap(self, action_name: str, tap_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Enforces double-tap confirmation within 3 seconds for emergency actions."""
        with self._lock:
            now = tap_time or datetime.now(timezone.utc)

            if self._pending_double_tap:
                pending_action = self._pending_double_tap["action"]
                pending_time = self._pending_double_tap["time"]

                # Check if second tap is within 3.0s window for the same action
                if pending_action == action_name and now - pending_time <= timedelta(seconds=3.0):
                    self._pending_double_tap = None
                    logger.critical(f"[MOBILE_UI] Double-tap confirmed! Executing {action_name}.")
                    return {
                        "is_confirmed": True,
                        "action": action_name,
                        "status": "EXECUTED",
                        "message": f"Emergency action '{action_name}' confirmed and executed.",
                    }

            # First tap: set pending confirmation
            self._pending_double_tap = {"action": action_name, "time": now}
            logger.warning(f"[MOBILE_UI] First emergency tap registered for {action_name}. Awaiting second tap within 3s.")
            return {
                "is_confirmed": False,
                "action": action_name,
                "status": "AWAITING_SECOND_TAP",
                "message": f"Double-tap confirmation required: tap again within 3 seconds to execute '{action_name}'.",
            }

    def render_mobile_view(self, is_offline: bool = False) -> MobileViewData:
        """Renders the mobile card view for the active tab."""
        with self._lock:
            cards: List[Dict[str, Any]] = []

            if self._active_tab == "home":
                cards = [
                    {"type": "SUMMARY", "title": "Portfolio Value", "value": f"${self._cached_state['trading_equity']:,.2f}"},
                    {"type": "STATUS", "title": "Active Systems", "subsystems": ["Trading", "Forge", "Nexus", "AI-Universe"]},
                ]
            elif self._active_tab == "trading":
                cards = [
                    {"type": "TRADING", "title": "Active Positions", "count": self._cached_state["active_positions"]},
                    {"type": "ACTION", "title": "Emergency Killswitch", "action_id": "EMERGENCY_HALT_TRADING"},
                ]
            elif self._active_tab == "forge":
                cards = [
                    {"type": "FORGE", "title": "Active Builds", "count": self._cached_state["forge_active_tasks"]},
                ]
            elif self._active_tab == "nexus":
                cards = [
                    {"type": "NEXUS", "title": "High-Intent Leads", "count": self._cached_state["nexus_leads_today"]},
                ]
            elif self._active_tab == "alerts":
                cards = [
                    {"type": "ALERT", "items": self._cached_state["recent_alerts"]},
                ]

            return MobileViewData(
                active_tab=self._active_tab,
                is_offline=is_offline,
                last_synced_at=self._last_sync.isoformat(),
                cards=cards,
                pending_emergency_action=self._pending_double_tap["action"] if self._pending_double_tap else None,
            )


# Default singleton instance
mobile_dashboard = MobileDashboardInterface()
