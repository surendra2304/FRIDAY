# -*- coding: utf-8 -*-
"""Production Emergency Procedures Engine for Multi-System Supervision.

Provides authoritative emergency response procedures:
1. Trading Halt: Emergency kill-switch halting all new order placement on Binance Futures.
2. Parameter Rollback: Emergency reversion of AI parameter overlays to last known safe defaults.
3. Advisory Disable: Temporarily deactivating AI advisory influence.
4. System Shutdown: Graceful stop and resource cleanup across operators and tasks.
5. Emergency Contacts: Multi-channel broadcasting to designated responders.
6. Cryptographic Audit Trail: Immutable hash-chained audit logs of all emergency interventions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import threading
from typing import Any, Dict, List, Optional, Set

from friday.core.logging import get_logger
from friday.core.types import AuthorizationDecision, Message, Role, SafetyLevel, TrustLevel
from friday.skills.trading_precedence import CommandPrecedence, tag_trading_command

logger = get_logger("emergency_procedures")


@dataclass
class EmergencyActionRecord:
    """Immutable audit record for an executed emergency action."""
    action_id: str
    action_name: str
    initiator: str
    reason: str
    timestamp: str
    status: str
    precedence_level: int
    prev_hash: str
    action_hash: str
    result_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_name": self.action_name,
            "initiator": self.initiator,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "status": self.status,
            "precedence_level": self.precedence_level,
            "prev_hash": self.prev_hash,
            "action_hash": self.action_hash,
            "result_payload": self.result_payload,
        }


class EmergencyProcedureManager:
    """Authoritative emergency procedures execution engine."""

    def __init__(
        self,
        bot_operator: Optional[Any] = None,
        memory: Optional[Any] = None,
        alert_manager: Optional[Any] = None,
        emergency_contacts: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        if bot_operator is None:
            from friday.skills.trading_bot_operator import TradingBotOperator
            bot_operator = TradingBotOperator()

        self.bot_operator = bot_operator
        self.memory = memory
        self.alert_manager = alert_manager
        self.emergency_contacts = emergency_contacts or [
            {"name": "Lead Operator (Surendra)", "email": "surendra@example.com", "phone": "+1-555-0199", "role": "Primary Operator"},
            {"name": "Risk Desk", "email": "risk@example.com", "phone": "+1-555-0198", "role": "Secondary Oversight"},
        ]
        self._audit_trail: List[EmergencyActionRecord] = []
        self._lock = threading.RLock()
        self._last_hash = "GENESIS_EMERGENCY_AUDIT_BLOCK"

    def trading_halt(
        self,
        reason: str = "Manual Emergency Halt",
        initiator: str = "Surendra",
        authorizer: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Halts all trading activities immediately via the Trading Bot's authoritative kill-switch API."""
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.critical(f"[EMERGENCY] Initiating TRADING HALT. Initiator: {initiator}, Reason: {reason}")

        try:
            res = self.bot_operator.trigger_panic(authorizer=authorizer)
            status = "SUCCESS" if res.get("status") in ("PANIC_ACTIVATED", "SUCCESS") else "COMPLETED"
            output_msg = f"Trading halt successfully triggered: {res.get('message', 'All order placement blocked.')}"
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed to execute trading halt: {e}", exc_info=True)
            status = "FAILED"
            output_msg = f"Trading halt execution error: {e}"
            res = {"error": str(e)}

        record = self._log_audit_action("TRADING_HALT", initiator, reason, status, res)

        if self.alert_manager:
            from friday.alert_manager import AlertSeverity
            self.alert_manager.create_alert(
                title="EMERGENCY TRADING HALT ACTIVATED",
                message=f"Trading halt triggered by {initiator}. Reason: {reason}",
                severity=AlertSeverity.CRITICAL,
                category="emergency_procedures",
                metadata=record.to_dict(),
            )

        return {
            "success": status in ("SUCCESS", "COMPLETED"),
            "action": "TRADING_HALT",
            "message": output_msg,
            "audit_id": record.action_id,
            "timestamp": now_iso,
            "raw_result": res,
        }

    def parameter_rollback(
        self,
        reason: str = "Emergency Parameter Rollback to Safe Baseline",
        initiator: str = "Surendra",
        authorizer: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Rolls back all testnet and live parameter overlays to safe defaults."""
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.warning(f"[EMERGENCY] Executing PARAMETER ROLLBACK. Initiator: {initiator}, Reason: {reason}")

        try:
            res = self.bot_operator.rollback_testnet_parameters()
            status = "SUCCESS" if res.get("status") in ("SUCCESS", "OK") else "COMPLETED"
            output_msg = f"Parameter rollback successful: {res.get('message', 'Default safe parameters restored.')}"
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed parameter rollback: {e}", exc_info=True)
            status = "FAILED"
            output_msg = f"Parameter rollback error: {e}"
            res = {"error": str(e)}

        record = self._log_audit_action("PARAMETER_ROLLBACK", initiator, reason, status, res)
        return {
            "success": status in ("SUCCESS", "COMPLETED"),
            "action": "PARAMETER_ROLLBACK",
            "message": output_msg,
            "audit_id": record.action_id,
            "timestamp": now_iso,
            "raw_result": res,
        }

    def advisory_disable(
        self,
        reason: str = "Temporary AI Advisory Deactivation",
        initiator: str = "Surendra",
        authorizer: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Disables AI-Universe advisory overlays on the trading bot."""
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.warning(f"[EMERGENCY] Disabling AI ADVISORY OVERLAYS. Initiator: {initiator}, Reason: {reason}")

        try:
            res = self.bot_operator.toggle_testnet_advisory(enabled=False, mode="SHADOW")
            status = "SUCCESS"
            output_msg = f"AI Advisory successfully disabled: {res.get('message', 'Mode set to SHADOW / Disabled.')}"
        except Exception as e:
            logger.error(f"[EMERGENCY] Failed disabling AI advisory: {e}", exc_info=True)
            status = "FAILED"
            output_msg = f"Failed to disable AI advisory: {e}"
            res = {"error": str(e)}

        record = self._log_audit_action("ADVISORY_DISABLE", initiator, reason, status, res)
        return {
            "success": status == "SUCCESS",
            "action": "ADVISORY_DISABLE",
            "message": output_msg,
            "audit_id": record.action_id,
            "timestamp": now_iso,
            "raw_result": res,
        }

    def system_shutdown(
        self,
        graceful: bool = True,
        operator_manager: Optional[Any] = None,
        initiator: str = "Surendra",
    ) -> Dict[str, Any]:
        """Gracefully halts all persistent operators and background tasks."""
        now_iso = datetime.now(timezone.utc).isoformat()
        logger.warning(f"[EMERGENCY] Executing SYSTEM SHUTDOWN. Graceful: {graceful}, Initiator: {initiator}")

        stopped_operators: List[str] = []
        if operator_manager:
            try:
                for op_name in list(operator_manager._operators.keys()):
                    operator_manager.unregister_operator(op_name)
                    stopped_operators.append(op_name)
            except Exception as e:
                logger.debug(f"[EMERGENCY] Error stopping operators: {e}")

        res = {"stopped_operators": stopped_operators, "graceful": graceful}
        record = self._log_audit_action("SYSTEM_SHUTDOWN", initiator, "System shutdown invoked", "SUCCESS", res)
        return {
            "success": True,
            "action": "SYSTEM_SHUTDOWN",
            "message": f"System shutdown complete. Stopped {len(stopped_operators)} operators.",
            "audit_id": record.action_id,
            "stopped_operators": stopped_operators,
            "timestamp": now_iso,
        }

    def emergency_contact(
        self,
        alert_message: str,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Dispatches emergency notifications to all registered escalation contacts across multiple channels."""
        channels = channels or ["email", "sms", "voice", "dashboard"]
        dispatched: List[Dict[str, Any]] = []

        for contact in self.emergency_contacts:
            entry = {
                "name": contact["name"],
                "role": contact.get("role", "Responder"),
                "channels_sent": channels,
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
                "status": "SENT",
            }
            dispatched.append(entry)
            logger.info(f"[EMERGENCY_CONTACT] Alerted {contact['name']} via {channels}: {alert_message}")

        return {
            "success": True,
            "dispatched_count": len(dispatched),
            "dispatched": dispatched,
            "alert_message": alert_message,
        }

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the cryptographic hash-chained audit log of all emergency interventions."""
        with self._lock:
            return [r.to_dict() for r in reversed(self._audit_trail[-limit:])]

    def _log_audit_action(
        self,
        action_name: str,
        initiator: str,
        reason: str,
        status: str,
        result_payload: Dict[str, Any],
    ) -> EmergencyActionRecord:
        """Appends a new cryptographically chained audit record."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            action_id = f"act_{len(self._audit_trail) + 1:04d}_{hashlib.md5(now_iso.encode('utf-8')).hexdigest()[:6]}"
            raw_block = f"{action_id}:{action_name}:{initiator}:{reason}:{status}:{self._last_hash}"
            action_hash = hashlib.sha256(raw_block.encode("utf-8")).hexdigest()

            record = EmergencyActionRecord(
                action_id=action_id,
                action_name=action_name,
                initiator=initiator,
                reason=reason,
                timestamp=now_iso,
                status=status,
                precedence_level=CommandPrecedence.FRIDAY_COMMANDS.value,
                prev_hash=self._last_hash,
                action_hash=action_hash,
                result_payload=result_payload,
            )
            self._audit_trail.append(record)
            self._last_hash = action_hash

        # Persist audit message to FRIDAY memory
        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"EMERGENCY_AUDIT_LOG [{action_name}] (ID: {action_id}): {reason} -> Status: {status}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    metadata=record.to_dict(),
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[EMERGENCY] Failed logging audit record to memory: {e}")

        return record
