"""Real Windows OS integration tests for Win32 SendInput and ComputerActionExecutor.

Exercises:
1. Native display metrics and cursor position queries.
2. Harmless Win32 cursor positioning and post-execution position verification.
3. Genuine physical execution path in `ComputerActionExecutor(sandboxed=False)`.
4. Proof that physical execution reports `is_physical_execution=True` and `is_sandboxed=False`.
5. Proof that prohibited actions are hard-blocked before reaching Win32 API.
"""

import sys

import pytest

from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.computer_control import (
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.windows_input_driver import (
    WindowsNativeInputDriver,
    check_desktop_interactivity,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows native input synthesis requires Windows OS host",
)


def test_windows_native_driver_metrics_and_cursor_query():
    """Verify that native Win32 driver correctly queries screen dimensions and cursor coordinates."""
    driver = WindowsNativeInputDriver()
    width, height = driver.get_screen_dimensions()
    assert width > 0, f"Expected positive screen width, got {width}"
    assert height > 0, f"Expected positive screen height, got {height}"

    cursor_x, cursor_y = driver.get_cursor_position()
    assert isinstance(cursor_x, int)
    assert isinstance(cursor_y, int)


def test_windows_native_driver_harmless_cursor_move_and_verify():
    """Verify physical cursor movement and assert GetCursorPos reflects new location when desktop is interactive."""
    is_interactive, reason = check_desktop_interactivity()
    if not is_interactive:
        pytest.skip(f"Physical input synthesis skipped: {reason}")

    driver = WindowsNativeInputDriver()
    width, height = driver.get_screen_dimensions()

    # Target a safe coordinate near the top-left region
    target_x = min(200, width - 10)
    target_y = min(200, height - 10)

    # Perform physical move
    ok = driver.move_cursor(target_x, target_y)
    assert ok is True

    # Query back position from Win32
    new_x, new_y = driver.get_cursor_position()
    assert abs(new_x - target_x) <= 2, f"Expected cursor X near {target_x}, got {new_x}"
    assert abs(new_y - target_y) <= 2, f"Expected cursor Y near {target_y}, got {new_y}"


def test_physical_computer_action_executor_move_execution():
    """Verify ComputerActionExecutor in physical mode genuinely moves cursor and records verification when interactive."""
    is_interactive, reason = check_desktop_interactivity()
    if not is_interactive:
        pytest.skip(f"Physical ComputerActionExecutor skipped: {reason}")

    executor = ComputerActionExecutor(sandboxed=False)
    assert executor.sandboxed is False

    width, height = executor.driver.get_screen_dimensions()
    target_x = min(250, width - 10)
    target_y = min(250, height - 10)

    prop = ComputerActionProposal(
        action_type=ActionType.MOVE,
        arguments={"x": target_x, "y": target_y},
        intent="Move cursor to test target area",
        requires_confirmation=False,
    )

    res = executor.execute_proposal(prop)
    assert res.status == ExecutionStatus.EXECUTED
    assert res.is_success is True
    assert res.is_physical_execution is True
    assert res.is_sandboxed is False
    assert res.verification_details is not None
    assert res.verification_details["coords_match"] is True
    assert prop.is_executed is True


def test_physical_computer_action_executor_blocks_prohibited_actions():
    """Verify that physical executor strictly blocks dangerous actions before touching Win32 APIs."""
    executor = ComputerActionExecutor(sandboxed=False)

    # Destructive command
    prop_bad = ProposalBuilder.type_text(
        text="format d: /fs:NTFS /q",
        intent="Quick format D drive",
    )
    res_bad = executor.execute_proposal(prop_bad, user_confirmed=True)
    assert res_bad.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_bad.is_success is False
    assert res_bad.is_physical_execution is False
    assert prop_bad.is_executed is False

    # Credential entry
    prop_cred = ProposalBuilder.type_text(
        text="AIzaSyA1234567890abcdefghijklmnopqrstuv",
        intent="Type private API key",
    )
    res_cred = executor.execute_proposal(prop_cred, user_confirmed=True)
    assert res_cred.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_cred.is_success is False


def test_physical_computer_action_executor_rejects_out_of_bounds():
    """Verify physical executor rejects coordinates exceeding actual display dimensions."""
    executor = ComputerActionExecutor(sandboxed=False)
    width, height = executor.driver.get_screen_dimensions()

    prop_oob = ComputerActionProposal(
        action_type=ActionType.CLICK,
        arguments={"x": width + 1000, "y": height + 1000},
        intent="Click coordinates outside primary monitor",
        requires_confirmation=True,
    )
    res_oob = executor.execute_proposal(prop_oob, user_confirmed=True)
    assert res_oob.status == ExecutionStatus.BLOCKED_OUT_OF_BOUNDS
    assert res_oob.is_success is False
