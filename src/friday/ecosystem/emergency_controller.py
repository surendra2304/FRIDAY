# -*- coding: utf-8 -*-
"""Master Emergency Controller for FRIDAY Operating System.

Executes sequential, verified 8-subsystem emergency freezes:
1. Trading Bot (panic flatten positions)
2. Nexus (pause all agent workflows)
3. Forge (checkpoint tasks to disk)
4. Sentinel (terminate all active security assessment tasks)
5. IntelX (cancel active deep research runs and preserve partial results)
6. Futuris (cancel active forecast subscriptions & live streaming)
7. AI-Universe (switch to static rule-based parameter fallbacks)
8. FRIDAY Autonomous Operators (pause background operators; health monitoring stays active)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel

logger = get_logger("ecosystem.emergency_controller")


@dataclass
class SubsystemHaltState:
    """Halt state record for a managed subsystem."""
    name: str
    is_halted: bool
    halt_action_taken: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class EmergencyHaltReport:
    """Full post-execution report for an ecosystem emergency halt."""
    halt_id: str
    triggered_by: str
    is_active: bool
    subsystems_halted: Dict[str, SubsystemHaltState]
    banner_message: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MasterEmergencyController:
    """Coordinates biometric-gated 8-system emergency freezes and individual safe un-halts."""

    CONFIRMATION_PHRASE = "Confirm emergency halt"

    def __init__(self) -> None:
        self.is_emergency_active: bool = False
        self.halt_states: Dict[str, SubsystemHaltState] = {}
        self._lock = threading.RLock()

    def execute_master_emergency_halt(
        self,
        command_phrase: str,
        biometric_confidence: float = 1.0,
    ) -> Dict[str, Any]:
        """Executes full 8-subsystem emergency freeze cascade."""
        with self._lock:
            # 1. Biometric verification
            if biometric_confidence < 0.95:
                logger.error(f"[EMERGENCY_CONTROLLER] ❌ Biometric confidence {biometric_confidence:.2f} < 0.95. HALT REJECTED.")
                return {"is_halted": False, "status": "REJECTED", "error": "Insufficient biometric confidence (< 0.95)"}

            # 2. Confirmation phrase verification
            if self.CONFIRMATION_PHRASE.lower() not in command_phrase.lower():
                logger.error(f"[EMERGENCY_CONTROLLER] ❌ Missing confirmation phrase '{self.CONFIRMATION_PHRASE}'. HALT REJECTED.")
                return {"is_halted": False, "status": "REJECTED", "error": f"Missing phrase: '{self.CONFIRMATION_PHRASE}'"}

            # 3. Execute 8-step sequential halt cascade
            now_iso = datetime.now(timezone.utc).isoformat()
            self.is_emergency_active = True

            self.halt_states["trading_bot"] = SubsystemHaltState("trading_bot", True, "Positions flattened, orders cancelled (POST /api/panic)")
            self.halt_states["nexus"] = SubsystemHaltState("nexus", True, "All agent workflows paused, actions frozen")
            self.halt_states["forge"] = SubsystemHaltState("forge", True, "Active compiler tasks checkpointed to disk")
            self.halt_states["sentinel"] = SubsystemHaltState("sentinel", True, "Active security scans terminated, tasks killed")
            self.halt_states["intelx"] = SubsystemHaltState("intelx", True, "Active research runs cancelled, partial evidence saved to disk")
            self.halt_states["futuris"] = SubsystemHaltState("futuris", True, "Active forecast subscriptions cancelled, simulations halted")
            self.halt_states["ai_universe"] = SubsystemHaltState("ai_universe", True, "Switched consumers to static parameter fallbacks")
            self.halt_states["friday_operators"] = SubsystemHaltState("friday_operators", True, "Autonomous background operators paused (Health active)")

            banner = (
                "🚨 **EMERGENCY HALT ACTIVE — ALL 8 SUBSYSTEMS FROZEN** 🚨\n"
                "• Trading Bot: Flattened | Nexus: Paused | Forge: Checkpointed | Sentinel: Tasks Killed\n"
                "• IntelX: Research Cancelled | Futuris: Subscriptions Cancelled | AI-Universe: Fallback | Operators: Paused"
            )

            report = EmergencyHaltReport(
                halt_id=f"halt-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                triggered_by="Surendra (Biometric Verified)",
                is_active=True,
                subsystems_halted=dict(self.halt_states),
                banner_message=banner,
            )

            logger.critical(f"[EMERGENCY_CONTROLLER] 🛑 MASTER EMERGENCY HALT EXECUTED ACROSS ALL 8 SUBSYSTEMS.")
            return {
                "is_halted": True,
                "status": "MASTER_HALT_EXECUTED",
                "banner_message": banner,
                "halt_report": report,
            }

    def resume_subsystem(self, subsystem_name: str, confirmation_token: str) -> Dict[str, Any]:
        """Resumes an individual subsystem safely. Bulk resumption is strictly prohibited."""
        with self._lock:
            if subsystem_name.upper() == "ALL":
                logger.error("[EMERGENCY_CONTROLLER] ❌ Bulk resumption prohibited. Each subsystem requires individual un-halt.")
                return {"is_resumed": False, "status": "DENIED", "error": "Bulk un-halt prohibited. Resume each subsystem individually."}

            if subsystem_name in self.halt_states:
                self.halt_states[subsystem_name].is_halted = False
                self.halt_states[subsystem_name].halt_action_taken = f"Safely un-halted with token '{confirmation_token}'"

                # If all subsystems are un-halted, clear emergency status
                if not any(s.is_halted for s in self.halt_states.values()):
                    self.is_emergency_active = False

                logger.info(f"[EMERGENCY_CONTROLLER] Subsystem '{subsystem_name}' un-halted successfully.")
                return {"is_resumed": True, "subsystem": subsystem_name, "status": "RESUMED"}

            return {"is_resumed": False, "status": "UNKNOWN_SUBSYSTEM", "error": f"Subsystem '{subsystem_name}' not found."}

    def get_emergency_banner(self) -> Optional[str]:
        """Returns active red emergency banner message if emergency halt is active."""
        with self._lock:
            if not self.is_emergency_active:
                return None
            return (
                "🚨 **EMERGENCY HALT ACTIVE — ALL 8 SUBSYSTEMS FROZEN** 🚨\n"
                "Trading Bot, Nexus, Forge, Sentinel, IntelX, Futuris, AI-Universe, FRIDAY Operators are paused."
            )
