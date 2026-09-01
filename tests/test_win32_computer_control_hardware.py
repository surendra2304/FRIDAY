"""Hardware Integration Test Suite — Win32 Computer-Control Execution Path.

Proves the actual execution path from ComputerActionProposal → WindowsNativeInputDriver
→ OS input synthesis. Every test is honestly classified as one of:

  REAL PASS   — Win32 API call occurred and was verified against OS state
  BLOCKED     — Non-interactive/headless session; hardware test cannot run
  SIMULATED   — Sandboxed mock (no OS effect; explicitly labeled)
  FAIL        — Unexpected failure

Zero tolerance for silent simulation masquerading as real hardware success.

Tests:
  1. test_cursor_move_real_win32_or_blocked
  2. test_sandboxed_never_touches_os
  3. test_dangerous_password_action_permanently_blocked
  4. test_dangerous_shell_action_permanently_blocked
  5. test_stale_screen_timestamp_blocked
  6. test_replay_prevention_enforced
  7. test_out_of_bounds_coordinates_blocked
  8. test_execute_tool_guard_chain_on_safe_scroll
  9. test_missing_coordinates_for_click_blocked
 10. test_physical_move_verified_against_cursor_position
"""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from friday.security.authorization import tool_authorizer
from friday.tools.builtin.execute_computer_action import ExecuteComputerActionTool
from friday.vision.actions import ActionType, ProposalBuilder
from friday.vision.computer_control import (
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.windows_input_driver import (
    MockWindowsInputDriver,
    WindowsNativeInputDriver,
    check_desktop_interactivity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_ts() -> str:
    """Return an ISO-8601 UTC timestamp 1 second ago (within freshness window)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()


def _stale_ts() -> str:
    """Return an ISO-8601 UTC timestamp 60 seconds ago (outside freshness window)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()


def _issue_capability(tool_name: str, intent: str) -> str:
    """Issue a real HMAC capability and return it JSON-serialized."""
    cap = tool_authorizer.issue_capability(
        tool_name=tool_name,
        arguments={"intent": intent},
        safety_level=__import__("friday.core.types", fromlist=["SafetyLevel"]).SafetyLevel.SENSITIVE,
    )
    # Serialize as JSON dict for the tool parameter
    return json.dumps({
        "capability_id": cap.capability_id,
        "tool_name": cap.tool_name,
        "tool_call_id": cap.tool_call_id,
        "args_hash": cap.args_hash,
        "safety_level": cap.safety_level.value,
        "purpose": cap.purpose,
        "affected_resource": cap.affected_resource,
        "created_at": cap.created_at,
        "expires_at": cap.expires_at,
        "is_used": cap.is_used,
        "signature": cap.signature,
    })


# ---------------------------------------------------------------------------
# Test 1 — Real Win32 cursor move OR honest BLOCKED
# ---------------------------------------------------------------------------

class TestRealWin32CursorMove:
    """Proves that the physical Win32 execution path actually calls SetCursorPos/SendInput."""

    def test_cursor_move_real_win32_or_blocked(self):
        """Move cursor to (100, 100) on a live interactive desktop, verify position within 2px.

        Classification:
          REAL PASS  — SetCursorPos succeeded and GetCursorPos confirms target ±2px
          BLOCKED    — Non-interactive or headless session; execution cannot happen
        """
        interactive, reason = check_desktop_interactivity()
        if not interactive:
            pytest.skip(f"BLOCKED: Non-interactive desktop — {reason}")

        driver = WindowsNativeInputDriver()
        sw, sh = driver.get_screen_dimensions()
        assert sw > 0 and sh > 0, "GetSystemMetrics returned zero — screen not reachable"

        target_x, target_y = min(100, sw - 10), min(100, sh - 10)
        success = driver.move_cursor(target_x, target_y)
        assert success, "SetCursorPos/SendInput returned False — OS rejected move"

        time.sleep(0.05)
        cur_x, cur_y = driver.get_cursor_position()
        delta = abs(cur_x - target_x) + abs(cur_y - target_y)
        assert delta <= 4, (
            f"REAL PASS threshold violated: cursor at ({cur_x}, {cur_y}), "
            f"expected ({target_x}, {target_y}), delta={delta}"
        )
        # If we reach here: REAL PASS
        print(f"\n[REAL PASS] Cursor moved to ({cur_x}, {cur_y}), target=({target_x}, {target_y}), delta={delta}px")


# ---------------------------------------------------------------------------
# Test 2 — Sandboxed mode never touches OS
# ---------------------------------------------------------------------------

class TestSandboxedIsolation:
    """Proves MockWindowsInputDriver has zero OS effect and is explicitly labeled SIMULATED."""

    def test_sandboxed_never_touches_os(self):
        """Sandbox mode must never invoke driver methods and must report is_physical_execution=False."""
        driver = MockWindowsInputDriver()
        executor = ComputerActionExecutor(sandboxed=True, driver=driver)

        proposal = ProposalBuilder.click(x=200, y=300, intent="Test click (sandboxed)")
        result = executor.execute_proposal(proposal, user_confirmed=True)

        assert result.status == ExecutionStatus.EXECUTED
        assert result.is_physical_execution is False, (
            f"SIMULATED action must never report is_physical_execution=True. Got: {result.to_dict()}"
        )
        assert result.is_sandboxed is True

        # KEY INVARIANT: sandboxed mode returns early WITHOUT calling the driver.
        # An empty call_log proves zero OS effect.
        assert driver.call_log == [], (
            f"Sandbox mode must never invoke the OS driver. call_log={driver.call_log}"
        )
        assert result.verification_details == {"simulated": True}
        print("\n[SIMULATED] Sandboxed execution confirmed: driver.call_log is empty, simulated=True")


# ---------------------------------------------------------------------------
# Tests 3–4 — Dangerous actions permanently blocked at hard-policy layer
# ---------------------------------------------------------------------------

class TestHardPolicyBlocking:

    def test_dangerous_password_action_permanently_blocked(self):
        """Password-containing intent must be blocked by hard policy, never reaching driver."""
        driver = MockWindowsInputDriver()
        executor = ComputerActionExecutor(sandboxed=True, driver=driver)

        proposal = ProposalBuilder.type_text(
            text="hunter2",
            intent="Enter password into login form",
        )
        result = executor.execute_proposal(proposal, user_confirmed=True)

        assert result.status == ExecutionStatus.BLOCKED_HARD_POLICY, (
            f"Password action must be BLOCKED_HARD_POLICY, got: {result.status}"
        )
        assert result.is_success is False
        assert len(driver.call_log) == 0, "Hard-blocked action must never reach the driver"

    def test_dangerous_shell_action_permanently_blocked(self):
        """Shell-injection intent (rm -rf) must be blocked before any OS call."""
        driver = MockWindowsInputDriver()
        executor = ComputerActionExecutor(sandboxed=False, driver=driver)

        proposal = ProposalBuilder.type_text(
            text="rm -rf /",
            intent="Run cleanup script",
        )
        result = executor.execute_proposal(proposal, user_confirmed=True)

        assert result.status == ExecutionStatus.BLOCKED_HARD_POLICY
        assert len(driver.call_log) == 0, "Destructive command must never reach driver even in physical mode"


# ---------------------------------------------------------------------------
# Test 5 — Stale screen timestamp blocked by ExecuteComputerActionTool
# ---------------------------------------------------------------------------

class TestScreenFreshnessGuard:

    def test_stale_screen_timestamp_blocked(self):
        """Screen observation older than max_screen_age_seconds must be rejected before execution."""
        tool = ExecuteComputerActionTool(sandboxed=True, max_screen_age_seconds=10.0)
        intent = "Move cursor to safe position"
        cap_json = _issue_capability(tool.name, intent)

        result = tool.execute(
            action_type="move",
            intent=intent,
            screen_timestamp_iso=_stale_ts(),
            authorization_token=cap_json,
            x=100,
            y=100,
        )

        assert result.is_error is True
        assert "stale" in result.content.lower() or "BLOCKED" in result.content, (
            f"Expected stale-screen block message, got: {result.content}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Replay prevention
# ---------------------------------------------------------------------------

class TestReplayPrevention:

    def test_replay_prevention_enforced(self):
        """Executing the same proposal_id twice must produce BLOCKED_REPLAY_ATTEMPT on second call."""
        driver = MockWindowsInputDriver()
        executor = ComputerActionExecutor(sandboxed=True, driver=driver)

        proposal = ProposalBuilder.scroll(delta_y=3, intent="Test scroll")

        result1 = executor.execute_proposal(proposal, user_confirmed=True)
        assert result1.status == ExecutionStatus.EXECUTED

        result2 = executor.execute_proposal(proposal, user_confirmed=True)
        assert result2.status == ExecutionStatus.BLOCKED_REPLAY_ATTEMPT, (
            f"Second execution of same proposal must be BLOCKED_REPLAY_ATTEMPT, got: {result2.status}"
        )


# ---------------------------------------------------------------------------
# Test 7 — Out-of-bounds coordinates
# ---------------------------------------------------------------------------

class TestCoordinateBoundsValidation:

    def test_out_of_bounds_coordinates_blocked(self):
        """Coordinates exceeding screen dimensions must be blocked before any OS call."""
        driver = MockWindowsInputDriver(screen_width=1920, screen_height=1080)
        executor = ComputerActionExecutor(sandboxed=True, driver=driver)

        # Coordinates far outside 1920x1080 display
        proposal = ProposalBuilder.click(x=9999, y=9999, intent="Out of bounds click")
        result = executor.execute_proposal(proposal, user_confirmed=True)

        assert result.status == ExecutionStatus.BLOCKED_OUT_OF_BOUNDS, (
            f"Expected BLOCKED_OUT_OF_BOUNDS, got: {result.status}"
        )
        assert len(driver.call_log) == 0


# ---------------------------------------------------------------------------
# Test 8 — Full guard chain on safe scroll via ExecuteComputerActionTool
# ---------------------------------------------------------------------------

class TestExecuteToolGuardChain:

    def test_execute_tool_guard_chain_on_safe_scroll(self):
        """Scroll action with fresh timestamp and valid capability must pass all 5 guards."""
        tool = ExecuteComputerActionTool(sandboxed=True, max_screen_age_seconds=10.0)
        intent = "Scroll document down"
        cap_json = _issue_capability(tool.name, intent)

        result = tool.execute(
            action_type="scroll",
            intent=intent,
            screen_timestamp_iso=_fresh_ts(),
            authorization_token=cap_json,
            delta_y=3,
        )

        # Scroll is SAFE-level (requires_confirmation=False) so it should execute
        assert result.is_error is False, (
            f"Safe scroll with valid auth should succeed. Got: {result.content}"
        )
        assert "EXECUTED" in result.content


# ---------------------------------------------------------------------------
# Test 9 — Missing coordinates for spatial action
# ---------------------------------------------------------------------------

class TestCoordinatePresenceGuard:

    def test_missing_coordinates_for_click_blocked(self):
        """Click action without x,y coordinates must be blocked at Guard 3."""
        tool = ExecuteComputerActionTool(sandboxed=True)
        intent = "Click something"
        cap_json = _issue_capability(tool.name, intent)

        result = tool.execute(
            action_type="click",
            intent=intent,
            screen_timestamp_iso=_fresh_ts(),
            authorization_token=cap_json,
            # x and y intentionally omitted
        )

        assert result.is_error is True
        assert "coordinate" in result.content.lower() or "BLOCKED" in result.content


# ---------------------------------------------------------------------------
# Test 10 — Physical move verified via post-execution cursor read-back
# ---------------------------------------------------------------------------

class TestPhysicalMoveVerification:
    """End-to-end: ComputerActionExecutor(sandboxed=False) + WindowsNativeInputDriver → OS."""

    def test_physical_move_verified_against_cursor_position(self):
        """On an interactive desktop, cursor move must be confirmed by GetCursorPos read-back.

        Classification:
          REAL PASS — GetCursorPos confirms cursor within 2px of target after SetCursorPos
          BLOCKED   — Non-interactive session; skipped
        """
        interactive, reason = check_desktop_interactivity()
        if not interactive:
            pytest.skip(f"BLOCKED: {reason}")

        executor = ComputerActionExecutor(sandboxed=False)

        # Use a non-destructive coordinate (top-left region)
        proposal = ProposalBuilder.click.__func__ if hasattr(ProposalBuilder.click, "__func__") else None
        from friday.vision.actions import ComputerActionProposal
        move_proposal = ComputerActionProposal(
            action_type=ActionType.MOVE,
            arguments={"x": 150, "y": 150},
            intent="Harmless cursor move for hardware verification",
            risk_level=__import__("friday.core.types", fromlist=["SafetyLevel"]).SafetyLevel.SAFE,
            requires_confirmation=False,
        )

        result = executor.execute_proposal(move_proposal, user_confirmed=True)

        assert result.status == ExecutionStatus.EXECUTED, (
            f"Physical MOVE must EXECUTE on interactive desktop. Got: {result.status} — {result.details}"
        )
        assert result.is_physical_execution is True
        assert result.verification_details is not None

        coords_match = result.verification_details.get("coords_match", False)
        actual = result.verification_details.get("actual_coords", "unknown")
        target = result.verification_details.get("target_coords", "unknown")

        assert coords_match, (
            f"REAL PASS threshold violated: target={target}, actual={actual}. "
            "OS cursor position does not match requested coordinates."
        )
        print(f"\n[REAL PASS] Physical cursor moved: target={target}, actual={actual}")
