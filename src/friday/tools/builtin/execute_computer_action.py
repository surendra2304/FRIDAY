# -*- coding: utf-8 -*-
"""Safe Win32 Computer Action Execution Tool for FRIDAY.

Bridges ComputerActionProposal → ComputerActionExecutor with mandatory layered pre-execution guards:

Guard 1 — Authorization capability token (HMAC-validated, single-use via DefaultSecureAuthorizer)
Guard 2 — Screen freshness timestamp (screen observation must be ≤ 10 s old)
Guard 3 — Coordinate presence for all spatial actions
Guard 4 — Action-specific safety re-check (evaluates against HARD_BLOCKED_INTENTS patterns)
Guard 5 — ComputerActionExecutor full pipeline (replay, freshness, bounds, confirmation, sandboxing)

Execution is SANDBOXED by default (zero OS effect). Real Win32 synthesis is only active when
the FRIDAY settings or test harness explicitly opts in with sandboxed=False.

Permanently blocked at Guard 4 regardless of mode:
- passwords / API keys / tokens
- payment / financial transaction verbs
- destructive shell commands (rm -rf, format, drop database …)
- privilege escalation (UAC bypass, secedit, takeown …)
- dangerous hotkeys (Win+R, Ctrl+Alt+Del, Alt+F4 …)
"""

from datetime import datetime, timezone
from typing import Any, Optional

from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.computer_control import (
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.windows_input_driver import (
    check_desktop_interactivity,
)

logger = get_logger("tools.execute_computer_action")

# Maximum age of the screen observation that grounded the coordinates
_MAX_SCREEN_AGE_SECONDS: float = 10.0

# Actions that require spatial coordinates
_SPATIAL_ACTIONS = frozenset({
    ActionType.CLICK,
    ActionType.DOUBLE_CLICK,
    ActionType.RIGHT_CLICK,
    ActionType.MOVE,
    ActionType.DRAG,
})


class ExecuteComputerActionTool(BaseTool):
    """SENSITIVE tool that executes a validated computer-action proposal via Win32 input synthesis.

    Safety model:
    - Five mandatory pre-execution guards (authorization, screen freshness, coordinates, policy, executor)
    - Sandboxed by default — zero OS effect unless physical=True is explicitly configured
    - All blocked actions return structured error results; none raise unhandled exceptions
    - Audit log persisted on the executor instance for post-turn inspection
    """

    name = "execute_computer_action"
    description = (
        "Execute a previously validated computer action (click, move, scroll, key_press) on "
        "the Windows desktop. Requires a valid screen_timestamp (taken within the last 10 s), "
        "explicit authorization_token, and passes through hard-policy safety checks before any "
        "OS input event is synthesized. Sandboxed by default."
    )
    safety_level = SafetyLevel.SENSITIVE

    parameters = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["click", "double_click", "right_click", "move", "type", "key_press", "hotkey", "scroll"],
                "description": "Type of computer action to execute.",
            },
            "intent": {
                "type": "string",
                "description": "Plain-English description of what this action intends to accomplish.",
            },
            "x": {
                "type": "integer",
                "description": "Target X pixel coordinate (required for click/move/drag). Omit for automatic screen centering if intent specifies 'center'.",
            },
            "y": {
                "type": "integer",
                "description": "Target Y pixel coordinate (required for click/move/drag). Omit for automatic screen centering if intent specifies 'center'.",
            },
            "text": {
                "type": "string",
                "description": "Text to type (required for 'type' action).",
            },
            "key": {
                "type": "string",
                "description": "Key name or '+'-separated hotkey combo (required for key_press/hotkey).",
            },
            "delta_y": {
                "type": "integer",
                "description": "Vertical scroll delta in wheel notches (required for scroll).",
            },
            "screen_timestamp_iso": {
                "type": "string",
                "description": (
                    "ISO-8601 UTC timestamp of the screen observation that grounded these coordinates. "
                    "Must be within the last 10 seconds. Example: '2026-08-21T10:00:00+00:00'"
                ),
            },
            "authorization_token": {
                "type": "string",
                "description": "Single-use HMAC authorization capability token issued for this action.",
            },
        },
        "required": ["action_type", "intent", "screen_timestamp_iso", "authorization_token"],
    }

    def __init__(
        self,
        sandboxed: bool = True,
        authorizer: Optional[BaseAuthorizer] = None,
        max_screen_age_seconds: float = _MAX_SCREEN_AGE_SECONDS,
    ) -> None:
        super().__init__()
        self.sandboxed = sandboxed
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.max_screen_age_seconds = max_screen_age_seconds

        # Build executor with appropriate driver
        if sandboxed:
            self._executor = ComputerActionExecutor(sandboxed=True)
        else:
            interactive, reason = check_desktop_interactivity()
            if not interactive:
                logger.warning(
                    f"Non-interactive desktop detected ({reason}); "
                    "ExecuteComputerActionTool forced to sandboxed mode."
                )
                self._executor = ComputerActionExecutor(sandboxed=True)
                self.sandboxed = True  # Override to prevent false physical claims
            else:
                self._executor = ComputerActionExecutor(sandboxed=False)

    # ------------------------------------------------------------------
    # Guard helpers
    # ------------------------------------------------------------------

    def _guard_authorization(self, token: str, intent: str) -> Optional[str]:
        """Guard 1: Deserialize and verify an HMAC-signed ToolAuthorizationCapability.

        The caller must pass the JSON-serialized capability issued by
        ToolAuthorizer.issue_capability() for this tool name.  The capability
        is consumed atomically — replay attempts are rejected.

        Returns an error string on failure, None on success.
        """
        import json
        try:
            from friday.security.authorization import (
                ToolAuthorizationCapability,
                tool_authorizer,
            )
            cap_dict = json.loads(token)
            cap = ToolAuthorizationCapability(**cap_dict)
            ok, reason = tool_authorizer.verify_and_consume(
                capability=cap,
                tool_name=self.name,
                arguments={"intent": intent},
            )
            if not ok:
                return f"Authorization denied: {reason}"
            return None
        except json.JSONDecodeError as exc:
            return f"Authorization token is not valid JSON: {exc}"
        except Exception as exc:
            return f"Authorization check failed: {exc}"

    def _guard_screen_freshness(self, screen_timestamp_iso: str) -> Optional[str]:
        """Guard 2: Ensure screen observation is recent enough to trust coordinates.

        Returns an error string on failure, None on success.
        """
        try:
            ts = datetime.fromisoformat(screen_timestamp_iso)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > self.max_screen_age_seconds:
                return (
                    f"Screen observation is stale (age={age:.1f}s > max={self.max_screen_age_seconds}s). "
                    "Capture a fresh screenshot before executing spatial actions."
                )
            return None
        except Exception as exc:
            return f"Invalid screen_timestamp_iso format: {exc}"

    def _guard_coordinates(self, act_enum: ActionType, x: Optional[int], y: Optional[int]) -> Optional[str]:
        """Guard 3: Require coordinates for all spatial actions."""
        if act_enum in _SPATIAL_ACTIONS:
            if x is None or y is None:
                return (
                    f"Action '{act_enum.value}' requires both 'x' and 'y' pixel coordinates. "
                    "Capture a fresh screenshot, identify the target element coordinates, then retry."
                )
        return None

    def _build_proposal(
        self,
        act_enum: ActionType,
        intent: str,
        x: Optional[int],
        y: Optional[int],
        text: Optional[str],
        key: Optional[str],
        delta_y: Optional[int],
    ) -> ComputerActionProposal:
        """Construct a proposal from execution parameters (no OS effect)."""
        if act_enum in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            return ProposalBuilder.click(
                x=int(x),
                y=int(y),
                intent=intent,
                double=(act_enum == ActionType.DOUBLE_CLICK),
                right=(act_enum == ActionType.RIGHT_CLICK),
            )
        elif act_enum == ActionType.MOVE:
            return ComputerActionProposal(
                action_type=ActionType.MOVE,
                arguments={"x": int(x), "y": int(y)},
                intent=intent,
                risk_level=SafetyLevel.SAFE,
                requires_confirmation=False,
            )
        elif act_enum == ActionType.TYPE:
            return ProposalBuilder.type_text(text=str(text), intent=intent)
        elif act_enum == ActionType.KEY_PRESS:
            return ProposalBuilder.key_press(key=str(key), intent=intent)
        elif act_enum == ActionType.HOTKEY:
            keys = [k.strip() for k in (key or "").split("+") if k.strip()]
            return ProposalBuilder.hotkey(keys=keys, intent=intent)
        elif act_enum == ActionType.SCROLL:
            return ProposalBuilder.scroll(delta_y=int(delta_y or 3), x=x, y=y, intent=intent)
        else:
            return ComputerActionProposal(
                action_type=act_enum,
                arguments={"x": x, "y": y},
                intent=intent,
                risk_level=SafetyLevel.SENSITIVE,
                requires_confirmation=True,
            )

    # ------------------------------------------------------------------
    # BaseTool.execute
    # ------------------------------------------------------------------

    def execute(
        self,
        action_type: str,
        intent: str,
        screen_timestamp_iso: str,
        authorization_token: str,
        x: Optional[int] = None,
        y: Optional[int] = None,
        text: Optional[str] = None,
        key: Optional[str] = None,
        delta_y: Optional[int] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a computer action through five mandatory pre-execution guards."""

        # ── Parse action type ────────────────────────────────────────────
        try:
            act_enum = ActionType(action_type.lower().strip())
        except ValueError:
            return ToolResult(
                name=self.name,
                content=f"Unknown action_type '{action_type}'. Supported: {[a.value for a in ActionType]}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # ── Guard 1: Authorization ───────────────────────────────────────
        auth_err = self._guard_authorization(authorization_token, intent)
        if auth_err:
            logger.warning(f"[GUARD-1 FAIL] {auth_err}")
            return ToolResult(
                name=self.name,
                content=f"BLOCKED (authorization): {auth_err}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # ── Guard 2: Screen freshness ────────────────────────────────────
        freshness_err = self._guard_screen_freshness(screen_timestamp_iso)
        if freshness_err:
            logger.warning(f"[GUARD-2 FAIL] {freshness_err}")
            return ToolResult(
                name=self.name,
                content=f"BLOCKED (stale screen): {freshness_err}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # ── Guard 3: Coordinate presence & Center resolution ────────────────
        if x is None and y is None and "center" in intent.lower():
            try:
                from friday.vision.windows_screen import WindowsScreenCaptureProvider
                displays = WindowsScreenCaptureProvider.list_displays()
                if displays:
                    x = displays[0]["width"] // 2
                    y = displays[0]["height"] // 2
                else:
                    x = 1920 // 2
                    y = 1080 // 2
            except Exception:
                x = 1920 // 2
                y = 1080 // 2

        coord_err = self._guard_coordinates(act_enum, x, y)
        if coord_err:
            logger.warning(f"[GUARD-3 FAIL] {coord_err}")
            return ToolResult(
                name=self.name,
                content=f"BLOCKED (missing coordinates): {coord_err}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # ── Guard 4: Build proposal + hard-policy safety re-check ────────
        proposal = self._build_proposal(act_enum, intent, x, y, text, key, delta_y)
        block_reason = self._executor.evaluate_safety_policy(proposal)
        if block_reason:
            logger.warning(f"[GUARD-4 FAIL] Hard-policy blocked: {block_reason}")
            return ToolResult(
                name=self.name,
                content=f"BLOCKED (hard safety policy): {block_reason}",
                is_error=True,
                safety_level=self.safety_level,
            )

        # ── Guard 5: Executor pipeline (replay, bounds, confirmation) ─────
        # MOVE and SCROLL are pre-confirmed (low risk); all others require explicit confirmation.
        user_confirmed = act_enum in (ActionType.MOVE, ActionType.SCROLL)
        exec_result = self._executor.execute_proposal(proposal, user_confirmed=user_confirmed)

        # ── Format result ─────────────────────────────────────────────────
        is_err = exec_result.status != ExecutionStatus.EXECUTED
        mode_tag = "SANDBOX" if self.sandboxed else "PHYSICAL"
        content_lines = [
            f"[{mode_tag}] Action: {exec_result.action_type}",
            f"Status: {exec_result.status.value}",
            f"Success: {exec_result.is_success}",
            f"Details: {exec_result.details}",
        ]
        if exec_result.verification_details:
            content_lines.append(f"Verification: {exec_result.verification_details}")

        return ToolResult(
            name=self.name,
            content="\n".join(content_lines),
            is_error=is_err,
            safety_level=self.safety_level,
        )

    @property
    def executor(self) -> ComputerActionExecutor:
        """Expose executor for test inspection of audit log."""
        return self._executor
