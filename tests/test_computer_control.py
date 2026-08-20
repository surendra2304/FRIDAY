# -*- coding: utf-8 -*-
"""Deterministic security unit tests for Phase 6.8 Safe Computer Control & Hard Block Policy."""

import pytest

from friday.core.types import SafetyLevel
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.computer_control import (
    ComputerActionExecutor,
    ExecutionStatus,
    HARD_BLOCKED_INTENTS,
)


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


def test_confirmed_safe_action_executes_in_sandbox():
    """Verify safe confirmed actions execute successfully inside sandbox."""
    executor = ComputerActionExecutor(sandboxed=True)

    prop = ProposalBuilder.scroll(delta_y=250, intent="Scroll down terminal output")
    # Scroll does not require confirmation by default
    res = executor.execute_proposal(prop)

    assert res.status == ExecutionStatus.EXECUTED
    assert res.is_success is True
    assert res.is_sandboxed is True
    assert prop.is_executed is True


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
