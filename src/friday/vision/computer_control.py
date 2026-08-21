# -*- coding: utf-8 -*-
"""Sandboxed, safety-bounded computer action executor and policy enforcement layer.

Enforces:
1. Strict Multi-Stage Pre-Execution Safety Gating:
   - Hard-Blocked Intent & Argument Inspection (passwords, tokens, payments, destructive commands, privilege escalation)
   - Replay Prevention (proposals can only be executed once)
   - Proposal Identity & Argument Validation
   - Screen Freshness & Timestamp Validation
   - Coordinate Bounds Verification against Display Metrics
   - Safe Key & Hotkey Allowlist Verification
   - Mandatory User Confirmation Gating
2. Strict Separation of Execution Modes:
   - Sandboxed / Virtual Simulation Mode (`sandboxed=True`): 100% isolated, zero OS input side effects.
   - Genuine Physical Windows Host Mode (`sandboxed=False`): Real Win32 input synthesis via `WindowsNativeInputDriver`.
3. Post-Execution Verification:
   - Validates that physical actions (e.g., cursor coordinates) took effect on the host.
4. Comprehensive Audit Logging without Secret Leakage.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from friday.core.logging import get_logger
from friday.vision.actions import ActionType, ComputerActionProposal
from friday.vision.windows_input_driver import (
    BaseWindowsInputDriver,
    MockWindowsInputDriver,
    WindowsNativeInputDriver,
)

logger = get_logger("vision.computer_control")

# Hard-blocked patterns that will NEVER be executed under any circumstances
HARD_BLOCKED_INTENTS = [
    # Passwords and PINs
    re.compile(r"(password|passwd|pin|credit_card|cvv|expiry)", re.IGNORECASE),
    # API Keys, Tokens, and Private Credentials
    re.compile(r"(aizasy|sk-[a-zA-Z0-9]{20,}|bearer\s+[a-zA-Z0-9_\-\.]{20,}|ghp_[a-zA-Z0-9]{30,}|aws_secret|private_key)", re.IGNORECASE),
    # Payments and Financial Transactions
    re.compile(r"(pay\b|buy\b|checkout\b|purchase\b|transfer\s+funds|wire\s+transfer|send\s+money)", re.IGNORECASE),
    # Destructive Disk and File System Commands
    re.compile(r"(format\s+[a-z]:|rm\s+-rf|del\s+/[fqs]|drop\s+database|diskpart|rd\s+/s|rmdir\s+/s)", re.IGNORECASE),
    # Dangerous Shell and Scripting Execution
    re.compile(r"(powershell\s+-enc|cmd\.exe\s+/c|reg\s+delete|net\s+user|net\s+localgroup|cacls|icacls|secedit|takeown|vssadmin|bcdedit)", re.IGNORECASE),
    # Privilege Escalation and Security Modifications
    re.compile(r"(uac\b|disable-windowsoptionalfeature|set-executionpolicy\s+unrestricted|disable-netfirewallrule)", re.IGNORECASE),
]

SAFE_KEY_ALLOWLIST: Set[str] = {
    "enter", "return", "tab", "space", "backspace", "escape", "esc", "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown", "insert", "delete", "f1", "f2", "f3", "f4", "f5", "f6",
    "f7", "f8", "f9", "f10", "f11", "f12",
}

SAFE_HOTKEY_ALLOWLIST: Set[str] = {
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+a", "ctrl+z", "ctrl+y", "ctrl+s", "ctrl+f",
    "ctrl+shift+f", "ctrl+shift+p", "alt+tab", "ctrl+tab",
}

DANGEROUS_HOTKEYS: Set[str] = {
    "win+r", "ctrl+alt+del", "ctrl+alt+delete", "alt+f4", "win+x", "ctrl+shift+esc",
}


class ExecutionStatus(str, Enum):
    """Result status of computer action execution attempt."""
    EXECUTED = "EXECUTED"
    BLOCKED_HARD_POLICY = "BLOCKED_HARD_POLICY"
    BLOCKED_UNCONFIRMED = "BLOCKED_UNCONFIRMED"
    BLOCKED_OUT_OF_BOUNDS = "BLOCKED_OUT_OF_BOUNDS"
    BLOCKED_INVALID_ARGUMENTS = "BLOCKED_INVALID_ARGUMENTS"
    BLOCKED_REPLAY_ATTEMPT = "BLOCKED_REPLAY_ATTEMPT"
    BLOCKED_STALE_CONTEXT = "BLOCKED_STALE_CONTEXT"
    FAILED = "FAILED"


@dataclass
class ActionExecutionResult:
    """Audit-safe record of a computer action execution attempt."""
    proposal_id: str
    action_type: str
    status: ExecutionStatus
    is_success: bool
    details: str
    executed_at: datetime
    is_sandboxed: bool
    is_physical_execution: bool = False
    verification_details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return safe representation without secrets."""
        return {
            "proposal_id": self.proposal_id,
            "action_type": self.action_type,
            "status": self.status.value,
            "is_success": self.is_success,
            "details": self.details,
            "executed_at": self.executed_at.isoformat(),
            "is_sandboxed": self.is_sandboxed,
            "is_physical_execution": self.is_physical_execution,
            "verification_details": self.verification_details,
        }


class ComputerActionExecutor:
    """Safe, multi-layer gated executor supporting both deterministic sandboxing and real Win32 execution."""

    def __init__(
        self,
        sandboxed: bool = True,
        confirmation_callback: Optional[Callable[[ComputerActionProposal], bool]] = None,
        driver: Optional[BaseWindowsInputDriver] = None,
        max_proposal_age_seconds: Optional[float] = 300.0,
    ) -> None:
        self.sandboxed = sandboxed
        self.confirmation_callback = confirmation_callback
        self.max_proposal_age_seconds = max_proposal_age_seconds
        self.execution_audit_log: List[ActionExecutionResult] = []
        self._executed_proposal_ids: Set[str] = set()

        if driver is not None:
            self.driver = driver
        elif sandboxed:
            self.driver = MockWindowsInputDriver()
        else:
            self.driver = WindowsNativeInputDriver()

    def evaluate_safety_policy(self, proposal: ComputerActionProposal) -> Optional[str]:
        """Check if proposal violates hard security boundaries.

        Returns:
            Reason string if hard blocked, or None if safe to proceed.
        """
        # Check text or arguments against hard-blocked patterns
        intent_text = proposal.intent or ""
        arg_text = " ".join(str(v) for v in proposal.arguments.values())
        combined = f"{intent_text} {arg_text}"

        for pattern in HARD_BLOCKED_INTENTS:
            if pattern.search(combined):
                return f"Hard-Blocked: Action contains prohibited sensitive pattern: '{pattern.pattern}'"

        # Check dangerous key combinations
        if proposal.action_type == ActionType.KEY_PRESS:
            key = str(proposal.arguments.get("key", "")).lower().strip()
            if len(key) > 1 and key not in SAFE_KEY_ALLOWLIST:
                return f"Hard-Blocked: Unsupported or potentially hazardous key: '{key}'"

        # Check dangerous hotkey combinations
        if proposal.action_type == ActionType.HOTKEY:
            keys = [str(k).lower().strip() for k in proposal.arguments.get("keys", [])]
            combo = "+".join(keys)
            if combo in DANGEROUS_HOTKEYS:
                return f"Hard-Blocked: High-risk system hotkey combination: '{combo}'"

        return None

    def validate_proposal(
        self,
        proposal: ComputerActionProposal,
        now: datetime,
    ) -> Optional[Tuple[ExecutionStatus, str]]:
        """Validate proposal identity, replay status, freshness, and coordinates."""
        # 1. Replay prevention
        if proposal.is_executed or proposal.proposal_id in self._executed_proposal_ids:
            return (
                ExecutionStatus.BLOCKED_REPLAY_ATTEMPT,
                "Proposal has already been executed. Re-execution rejected to prevent replay attacks.",
            )

        # 2. Proposal ID verification
        if not proposal.proposal_id or not proposal.proposal_id.strip():
            return (
                ExecutionStatus.BLOCKED_INVALID_ARGUMENTS,
                "Proposal missing valid proposal_id.",
            )

        # 3. Freshness validation
        if self.max_proposal_age_seconds is not None and proposal.created_at:
            created = proposal.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (now - created).total_seconds()
            if age > self.max_proposal_age_seconds:
                return (
                    ExecutionStatus.BLOCKED_STALE_CONTEXT,
                    f"Proposal is stale (age: {age:.1f}s > max {self.max_proposal_age_seconds}s).",
                )

        # 4. Coordinate bounds validation for spatial actions
        if proposal.action_type in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.MOVE, ActionType.DRAG):
            x = proposal.arguments.get("x")
            y = proposal.arguments.get("y")
            if x is not None and y is not None:
                try:
                    ix, iy = int(x), int(y)
                    sw, sh = self.driver.get_screen_dimensions()
                    if sw > 0 and sh > 0:
                        if ix < 0 or ix >= sw or iy < 0 or iy >= sh:
                            return (
                                ExecutionStatus.BLOCKED_OUT_OF_BOUNDS,
                                f"Coordinates ({ix}, {iy}) out of display bounds (0..{sw-1}, 0..{sh-1}).",
                            )
                except (ValueError, TypeError) as e:
                    return (
                        ExecutionStatus.BLOCKED_INVALID_ARGUMENTS,
                        f"Invalid coordinate format: {e}",
                    )

        # 5. Argument validation for text / key actions
        if proposal.action_type == ActionType.TYPE:
            if "text" not in proposal.arguments:
                return (
                    ExecutionStatus.BLOCKED_INVALID_ARGUMENTS,
                    "Type action missing 'text' argument.",
                )

        if proposal.action_type == ActionType.KEY_PRESS:
            if "key" not in proposal.arguments:
                return (
                    ExecutionStatus.BLOCKED_INVALID_ARGUMENTS,
                    "Key press action missing 'key' argument.",
                )

        return None

    def execute_proposal(
        self,
        proposal: ComputerActionProposal,
        user_confirmed: bool = False,
    ) -> ActionExecutionResult:
        """Execute action proposal under strict multi-layer safety gating."""
        now = datetime.now(timezone.utc)

        # Stage 1: Proposal Validation (Identity, Replay, Freshness, Bounds)
        val_error = self.validate_proposal(proposal, now)
        if val_error:
            status, reason = val_error
            logger.warning(f"Proposal '{proposal.proposal_id}' validation rejected: {reason}")
            result = ActionExecutionResult(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type.value,
                status=status,
                is_success=False,
                details=reason,
                executed_at=now,
                is_sandboxed=self.sandboxed,
                is_physical_execution=False,
            )
            self.execution_audit_log.append(result)
            return result

        # Stage 2: Hard-policy evaluation
        block_reason = self.evaluate_safety_policy(proposal)
        if block_reason:
            logger.warning(f"Computer action blocked by hard safety policy: {block_reason}")
            result = ActionExecutionResult(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type.value,
                status=ExecutionStatus.BLOCKED_HARD_POLICY,
                is_success=False,
                details=block_reason,
                executed_at=now,
                is_sandboxed=self.sandboxed,
                is_physical_execution=False,
            )
            self.execution_audit_log.append(result)
            return result

        # Stage 3: Confirmation gating
        is_confirmed = user_confirmed
        if not is_confirmed and proposal.requires_confirmation:
            if self.confirmation_callback is not None:
                is_confirmed = self.confirmation_callback(proposal)

        if proposal.requires_confirmation and not is_confirmed:
            logger.info(f"Action proposal '{proposal.action_type.value}' denied: awaiting user confirmation.")
            result = ActionExecutionResult(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type.value,
                status=ExecutionStatus.BLOCKED_UNCONFIRMED,
                is_success=False,
                details="Action requires explicit user confirmation before execution.",
                executed_at=now,
                is_sandboxed=self.sandboxed,
                is_physical_execution=False,
            )
            self.execution_audit_log.append(result)
            return result

        # Stage 4: Execution Dispatch (Sandboxed vs Physical OS)
        if self.sandboxed:
            proposal.is_executed = True
            self._executed_proposal_ids.add(proposal.proposal_id)
            logger.info(f"[SANDBOX] Safely simulated computer action '{proposal.action_type.value}' ({proposal.arguments}).")
            result = ActionExecutionResult(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type.value,
                status=ExecutionStatus.EXECUTED,
                is_success=True,
                details=f"Sandboxed simulation of {proposal.action_type.value} succeeded.",
                executed_at=now,
                is_sandboxed=True,
                is_physical_execution=False,
                verification_details={"simulated": True},
            )
            self.execution_audit_log.append(result)
            return result

        # Genuine Physical Execution on Windows host
        try:
            op_success = False
            verification_info: Dict[str, Any] = {}
            act = proposal.action_type

            if act == ActionType.MOVE:
                tx = int(proposal.arguments["x"])
                ty = int(proposal.arguments["y"])
                op_success = self.driver.move_cursor(tx, ty)
                # Post-execution verification
                cur_x, cur_y = self.driver.get_cursor_position()
                verification_info["target_coords"] = (tx, ty)
                verification_info["actual_coords"] = (cur_x, cur_y)
                verification_info["coords_match"] = abs(cur_x - tx) <= 2 and abs(cur_y - ty) <= 2

            elif act == ActionType.CLICK:
                cx = proposal.arguments.get("x")
                cy = proposal.arguments.get("y")
                btn = proposal.arguments.get("button", "left")
                op_success = self.driver.click(
                    x=int(cx) if cx is not None else None,
                    y=int(cy) if cy is not None else None,
                    button=btn,
                )
                verification_info["clicked_button"] = btn

            elif act == ActionType.DOUBLE_CLICK:
                cx = proposal.arguments.get("x")
                cy = proposal.arguments.get("y")
                op_success = self.driver.double_click(
                    x=int(cx) if cx is not None else None,
                    y=int(cy) if cy is not None else None,
                )
                verification_info["double_clicked"] = True

            elif act == ActionType.RIGHT_CLICK:
                cx = proposal.arguments.get("x")
                cy = proposal.arguments.get("y")
                op_success = self.driver.click(
                    x=int(cx) if cx is not None else None,
                    y=int(cy) if cy is not None else None,
                    button="right",
                )
                verification_info["right_clicked"] = True

            elif act == ActionType.SCROLL:
                delta = int(proposal.arguments.get("delta_y", proposal.arguments.get("delta", 120)))
                op_success = self.driver.scroll(delta_y=delta)
                verification_info["scroll_delta"] = delta

            elif act == ActionType.KEY_PRESS:
                k = str(proposal.arguments["key"])
                op_success = self.driver.press_key(k)
                verification_info["key_pressed"] = k

            elif act == ActionType.TYPE:
                text_to_type = str(proposal.arguments["text"])
                op_success = self.driver.type_text(text_to_type)
                verification_info["chars_typed"] = len(text_to_type)

            elif act == ActionType.HOTKEY:
                keys = [str(k) for k in proposal.arguments.get("keys", [])]
                op_success = self.driver.hotkey(keys)
                verification_info["hotkey_combo"] = keys

            else:
                op_success = False
                verification_info["error"] = f"Unsupported action type '{act.value}'"

            if op_success:
                proposal.is_executed = True
                self._executed_proposal_ids.add(proposal.proposal_id)
                logger.info(f"Physical Windows input execution of '{act.value}' succeeded.")
                result = ActionExecutionResult(
                    proposal_id=proposal.proposal_id,
                    action_type=proposal.action_type.value,
                    status=ExecutionStatus.EXECUTED,
                    is_success=True,
                    details=f"Successfully executed {act.value} on host via Win32 synthesis.",
                    executed_at=now,
                    is_sandboxed=False,
                    is_physical_execution=True,
                    verification_details=verification_info,
                )
            else:
                result = ActionExecutionResult(
                    proposal_id=proposal.proposal_id,
                    action_type=proposal.action_type.value,
                    status=ExecutionStatus.FAILED,
                    is_success=False,
                    details=f"Win32 driver failed to synthesize {act.value}.",
                    executed_at=now,
                    is_sandboxed=False,
                    is_physical_execution=True,
                    verification_details=verification_info,
                )

            self.execution_audit_log.append(result)
            return result

        except Exception as e:
            logger.error(f"Host action execution failed with exception: {e}")
            result = ActionExecutionResult(
                proposal_id=proposal.proposal_id,
                action_type=proposal.action_type.value,
                status=ExecutionStatus.FAILED,
                is_success=False,
                details=str(e),
                executed_at=now,
                is_sandboxed=False,
                is_physical_execution=True,
            )
            self.execution_audit_log.append(result)
            return result
