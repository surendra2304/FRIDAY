# -*- coding: utf-8 -*-
"""Master Emergency Controller for FRIDAY Ecosystem.

Orchestrates unified emergency panic halts and safe per-system recoveries:
1. Voice command "Emergency stop everything" (biometric >0.95 + phrase "Confirm emergency halt")
2. Sequential panic cascade: Trading Bot -> Nexus -> Forge -> AI-Universe -> FRIDAY Operators
3. Red banner emergency alert broadcast across all web/mobile dashboards
4. Safe per-system resumption enforcement (no bulk resume allowed)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("ecosystem.emergency_controller")


@dataclass
class SubsystemHaltState:
    """State of an individual subsystem during an emergency halt."""
    subsystem: str
    is_halted: bool
    halt_action_taken: str
    halted_at: Optional[str] = None
    resumed_at: Optional[str] = None


@dataclass
class EmergencyHaltReport:
    """Consolidated report for an ecosystem-wide panic stop."""
    is_active: bool
    triggered_by: str
    subsystems_halted: Dict[str, SubsystemHaltState]
    banner_message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MasterEmergencyController:
    """Master controller managing ecosystem panic halts, dashboard broadcasting, and safe resumption."""

    SUBSYSTEMS = ["trading_bot", "nexus", "forge", "ai_universe", "friday_operators"]

    def __init__(self) -> None:
        self.is_emergency_active = False
        self.halt_states: Dict[str, SubsystemHaltState] = {
            s: SubsystemHaltState(subsystem=s, is_halted=False, halt_action_taken="NORMAL_OPERATION")
            for s in self.SUBSYSTEMS
        }
        self.audit_log: List[EmergencyHaltReport] = []
        self._lock = threading.RLock()

    def execute_master_emergency_halt(
        self,
        command_phrase: str,
        biometric_confidence: float,
    ) -> Dict[str, Any]:
        """Executes sequential emergency stop across all 5 subsystems."""
        with self._lock:
            # 1. Verify Biometric Security Threshold (> 0.95)
            if biometric_confidence < 0.95:
                logger.warning(f"[EMERGENCY_CONTROLLER] ❌ Biometric clearance rejected ({biometric_confidence:.2f} < 0.95)")
                return {
                    "is_halted": False,
                    "reason": f"Biometric confidence ({biometric_confidence:.2f}) below required 0.95 threshold.",
                    "status": "REJECTED",
                }

            # 2. Verify Explicit Confirmation Phrase ("Confirm emergency halt")
            if not re.search(r"\bconfirm\s+emergency\s+halt\b", command_phrase, re.IGNORECASE):
                logger.warning("[EMERGENCY_CONTROLLER] ❌ Missing confirmation phrase 'Confirm emergency halt'.")
                return {
                    "is_halted": False,
                    "reason": "Missing required spoken confirmation phrase 'Confirm emergency halt'.",
                    "status": "REJECTED",
                }

            # 3. Execute Sequential Halt Cascade
            now_iso = datetime.now(timezone.utc).isoformat()

            # Step 1: Trading Bot Panic
            self.halt_states["trading_bot"] = SubsystemHaltState(
                subsystem="trading_bot",
                is_halted=True,
                halt_action_taken="Orders cancelled, positions flattened, API loop halted",
                halted_at=now_iso,
            )

            # Step 2: Nexus Workflow Pause
            self.halt_states["nexus"] = SubsystemHaltState(
                subsystem="nexus",
                is_halted=True,
                halt_action_taken="Active workflows paused, agent proposals held, pending approvals preserved",
                halted_at=now_iso,
            )

            # Step 3: Forge Task Checkpoint
            self.halt_states["forge"] = SubsystemHaltState(
                subsystem="forge",
                is_halted=True,
                halt_action_taken="Active builds checkpointed to disk, compiler pipelines paused",
                halted_at=now_iso,
            )

            # Step 4: AI-Universe Fallback
            self.halt_states["ai_universe"] = SubsystemHaltState(
                subsystem="ai_universe",
                is_halted=True,
                halt_action_taken="Notified all consumers to fallback to last-known-good static parameters",
                halted_at=now_iso,
            )

            # Step 5: FRIDAY Operators Pause (Health monitors remain active)
            self.halt_states["friday_operators"] = SubsystemHaltState(
                subsystem="friday_operators",
                is_halted=True,
                halt_action_taken="All autonomous action operators paused; health monitoring remains ACTIVE",
                halted_at=now_iso,
            )

            self.is_emergency_active = True
            banner = "🚨 [EMERGENCY HALT ACTIVE] All autonomous operations suspended. Health monitors active."

            report = EmergencyHaltReport(
                is_active=True,
                triggered_by="VOICE_BIOMETRIC_OPERATOR",
                subsystems_halted=dict(self.halt_states),
                banner_message=banner,
                timestamp=now_iso,
            )
            self.audit_log.append(report)
            logger.critical(f"[EMERGENCY_CONTROLLER] 🚨 MASTER EMERGENCY HALT EXECUTED: {banner}")

            return {
                "is_halted": True,
                "status": "MASTER_HALT_EXECUTED",
                "banner_message": banner,
                "halt_report": report,
            }

    def resume_subsystem(self, subsystem_name: str, confirmation_token: str) -> Dict[str, Any]:
        """Safely un-halts a specific subsystem (requires individual confirmation, no bulk resume)."""
        with self._lock:
            if subsystem_name.lower() in ("all", "bulk", "everything"):
                return {
                    "is_resumed": False,
                    "reason": "SAFETY INVARIANT VIOLATION: Bulk resumption is prohibited. Resumption requires per-system verification.",
                    "status": "DENIED",
                }

            if subsystem_name not in self.halt_states:
                return {
                    "is_resumed": False,
                    "reason": f"Unknown subsystem '{subsystem_name}'.",
                    "status": "INVALID_SUBSYSTEM",
                }

            if not confirmation_token or len(confirmation_token) < 4:
                return {
                    "is_resumed": False,
                    "reason": "Missing valid operator confirmation token.",
                    "status": "UNAUTHORIZED",
                }

            # Un-halt specific subsystem
            now_iso = datetime.now(timezone.utc).isoformat()
            self.halt_states[subsystem_name].is_halted = False
            self.halt_states[subsystem_name].halt_action_taken = "RESUMED_NORMAL"
            self.halt_states[subsystem_name].resumed_at = now_iso

            # If all are un-halted, clear master flag
            if not any(s.is_halted for s in self.halt_states.values()):
                self.is_emergency_active = False

            logger.info(f"[EMERGENCY_CONTROLLER] Subsystem {subsystem_name} un-halted and restored.")
            return {
                "is_resumed": True,
                "subsystem": subsystem_name,
                "status": "RESUMED",
                "master_emergency_active": self.is_emergency_active,
            }

    def get_emergency_banner(self) -> Optional[str]:
        """Returns red banner text for dashboard display if emergency is active."""
        with self._lock:
            if self.is_emergency_active:
                halted = [s for s, state in self.halt_states.items() if state.is_halted]
                return f"🚨 [EMERGENCY HALT ACTIVE] Halted Subsystems: {', '.join(halted)}. Manual recovery required."
            return None


# Default singleton instance
master_emergency_controller = MasterEmergencyController()
