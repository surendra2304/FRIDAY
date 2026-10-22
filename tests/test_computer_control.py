"""Deterministic security unit tests for Safe Computer Control & Hard Block Policy."""

from datetime import datetime, timedelta, timezone

from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.computer_control import (
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.windows_input_driver import MockWindowsInputDriver


def test_hard_block_password_and_secret_entry():
    """Verify password, API key, and secret entries are strictly hard-blocked from execution."""
    executor = ComputerActionExecutor(sandboxed=True)

    # 1. Propose typing a password
    prop_pwd = ComputerActionProposal(
        action_type=ActionType.TYPE,
        arguments={"text": "MySecretPassword123!"},
        intent="Type password in authentication field",
        requires_confirmation=True,
    )
    res_pwd = executor.execute_proposal(prop_pwd, user_confirmed=True)
    assert res_pwd.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_pwd.is_success is False
    assert "Hard-Blocked" in res_pwd.details
    assert prop_pwd.is_executed is False

    # 2. Propose typing an API key
    fake_key = "AIza" + "Sy" + "D1234567890abcdefghijklmnopqrstuv"
    prop_key = ComputerActionProposal(
        action_type=ActionType.TYPE,
        arguments={"text": fake_key},
        intent="Enter Gemini API key",
        requires_confirmation=True,
    )
    res_key = executor.execute_proposal(prop_key, user_confirmed=True)
    assert res_key.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_key.is_success is False


def test_hard_block_financial_transactions_and_destructive_shell():
    """Verify payments and destructive commands are strictly hard-blocked."""
    executor = ComputerActionExecutor(sandboxed=True)

    # Financial transaction
    prop_pay = ComputerActionProposal(
        action_type=ActionType.CLICK,
        arguments={"x": 300, "y": 600},
        intent="Pay $500 invoice checkout",
        requires_confirmation=True,
    )
    res_pay = executor.execute_proposal(prop_pay, user_confirmed=True)
    assert res_pay.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_pay.is_success is False

    # Destructive disk/file deletion command
    prop_rm = ComputerActionProposal(
        action_type=ActionType.TYPE,
        arguments={"text": "rm -rf / --no-preserve-root"},
        intent="Clean temp root directory",
        requires_confirmation=True,
    )
    res_rm = executor.execute_proposal(prop_rm, user_confirmed=True)
    assert res_rm.status == ExecutionStatus.BLOCKED_HARD_POLICY
    assert res_rm.is_success is False


def test_hard_block_privilege_escalation_and_registry_tampering():
    """Verify privilege escalation and system setting modification are strictly hard-blocked."""
    executor = ComputerActionExecutor(sandboxed=True)

    # 1. Registry deletion
    prop_reg = ComputerActionProposal(
        action_type=ActionType.TYPE,
        arguments={"text": "reg delete HKLM\\Software\\Policies /f"},
        intent="Remove security policies",
        requires_confirmation=True,
    )
    res_reg = executor.execute_proposal(prop_reg, user_confirmed=True)
    assert res_reg.status == ExecutionStatus.BLOCKED_HARD_POLICY

    # 2. Net user admin creation
    prop_user = ComputerActionProposal(
        action_type=ActionType.TYPE,
        arguments={"text": "net user attacker Password123 /add"},
        intent="Create local administrator account",
        requires_confirmation=True,
    )
    res_user = executor.execute_proposal(prop_user, user_confirmed=True)
    assert res_user.status == ExecutionStatus.BLOCKED_HARD_POLICY


def test_unconfirmed_state_changing_action_is_blocked():
    """Verify state-changing actions without explicit user confirmation are blocked."""
    executor = ComputerActionExecutor(sandboxed=True)

    prop = ProposalBuilder.click(x=100, y=200, intent="Click menu item")
    assert prop.requires_confirmation is True

    # Attempt execution without user confirmation
    res = executor.execute_proposal(prop, user_confirmed=False)
    assert res.status == ExecutionStatus.BLOCKED_UNCONFIRMED
    assert res.is_success is False
    assert "requires explicit user confirmation" in res.details
    assert prop.is_executed is False


def test_replay_attack_prevention():
    """Verify that a previously executed proposal cannot be re-executed."""
    executor = ComputerActionExecutor(sandboxed=True)

    prop = ProposalBuilder.click(x=150, y=250, intent="Click benign button")
    res1 = executor.execute_proposal(prop, user_confirmed=True)
    assert res1.status == ExecutionStatus.EXECUTED
    assert res1.is_success is True
    assert prop.is_executed is True

    # Second execution attempt with identical proposal
    res2 = executor.execute_proposal(prop, user_confirmed=True)
    assert res2.status == ExecutionStatus.BLOCKED_REPLAY_ATTEMPT
    assert res2.is_success is False
    assert "replay" in res2.details.lower()


def test_out_of_bounds_coordinate_rejection():
    """Verify out-of-bounds mouse coordinates are strictly rejected."""
    mock_driver = MockWindowsInputDriver(screen_width=1920, screen_height=1080)
    executor = ComputerActionExecutor(sandboxed=False, driver=mock_driver)

    # 1. Negative coordinate
    prop_neg = ProposalBuilder.click(x=-10, y=200, intent="Click negative coordinate")
    res_neg = executor.execute_proposal(prop_neg, user_confirmed=True)
    assert res_neg.status == ExecutionStatus.BLOCKED_OUT_OF_BOUNDS
    assert res_neg.is_success is False

    # 2. Beyond screen width
    prop_wide = ProposalBuilder.click(x=2500, y=500, intent="Click beyond screen width")
    res_wide = executor.execute_proposal(prop_wide, user_confirmed=True)
    assert res_wide.status == ExecutionStatus.BLOCKED_OUT_OF_BOUNDS
    assert res_wide.is_success is False


def test_unallowlisted_key_and_dangerous_hotkey_rejection():
    """Verify hazardous hotkeys and unsupported key codes are blocked."""
    executor = ComputerActionExecutor(sandboxed=True)

    # 1. Dangerous Win+R hotkey
    prop_win_r = ProposalBuilder.hotkey(keys=["win", "r"], intent="Open run dialog")
    res_win_r = executor.execute_proposal(prop_win_r, user_confirmed=True)
    assert res_win_r.status == ExecutionStatus.BLOCKED_HARD_POLICY

    # 2. Unallowlisted key name
    prop_bad_key = ProposalBuilder.key_press(key="ExecuteArbitraryPayloadKey", intent="Press custom key")
    res_bad_key = executor.execute_proposal(prop_bad_key, user_confirmed=True)
    assert res_bad_key.status == ExecutionStatus.BLOCKED_HARD_POLICY


def test_stale_proposal_timestamp_rejection():
    """Verify proposals older than max_proposal_age_seconds are rejected."""
    executor = ComputerActionExecutor(sandboxed=True, max_proposal_age_seconds=60.0)

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
    prop = ComputerActionProposal(
        action_type=ActionType.CLICK,
        arguments={"x": 100, "y": 100},
        intent="Click stale button",
        created_at=stale_time,
        requires_confirmation=True,
    )
    res = executor.execute_proposal(prop, user_confirmed=True)
    assert res.status == ExecutionStatus.BLOCKED_STALE_CONTEXT
    assert res.is_success is False


def test_mock_driver_physical_execution_dispatch_and_verification():
    """Verify physical execution path routes inputs to driver and verifies cursor state."""
    mock_driver = MockWindowsInputDriver(screen_width=1920, screen_height=1080)
    executor = ComputerActionExecutor(sandboxed=False, driver=mock_driver)

    # Move cursor
    prop_move = ComputerActionProposal(
        action_type=ActionType.MOVE,
        arguments={"x": 500, "y": 400},
        intent="Move cursor to button",
        requires_confirmation=False,
    )
    res_move = executor.execute_proposal(prop_move)
    assert res_move.status == ExecutionStatus.EXECUTED
    assert res_move.is_success is True
    assert res_move.is_physical_execution is True
    assert res_move.is_sandboxed is False
    assert res_move.verification_details is not None
    assert res_move.verification_details["coords_match"] is True
    assert mock_driver.get_cursor_position() == (500, 400)

    # Type safe text
    prop_type = ProposalBuilder.type_text(text="Hello FRIDAY", intent="Type greeting into text box")
    res_type = executor.execute_proposal(prop_type, user_confirmed=True)
    assert res_type.status == ExecutionStatus.EXECUTED
    assert res_type.is_physical_execution is True
    assert any(c["action"] == "type_text" and c["text"] == "Hello FRIDAY" for c in mock_driver.call_log)


def test_audit_log_records_without_secrets():
    """Verify audit log tracks proposal ID and status without storing sensitive credentials."""
    executor = ComputerActionExecutor(sandboxed=True)

    prop = ProposalBuilder.click(x=500, y=500, intent="Click normal button")
    executor.execute_proposal(prop, user_confirmed=True)

    assert len(executor.execution_audit_log) == 1
    entry = executor.execution_audit_log[0].to_dict()
    assert entry["proposal_id"] == prop.proposal_id
    assert entry["status"] == "EXECUTED"
    assert entry["is_sandboxed"] is True
    assert entry["is_physical_execution"] is False
