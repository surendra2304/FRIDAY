# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Ecosystem-Wide Kill Switch & Emergency Playbooks."""

import pytest

from friday.ecosystem.emergency_controller import MasterEmergencyController
from friday.ecosystem.playbooks import EmergencyPlaybookSystem
from friday.operators.cascade_detector import CascadeFailureDetector


@pytest.fixture
def emergency_setup():
    controller = MasterEmergencyController()
    cascade = CascadeFailureDetector()
    playbooks = EmergencyPlaybookSystem()

    return controller, cascade, playbooks


# =========================================================================
# 1. Master Emergency Controller & Sequential Freeze Tests
# =========================================================================

def test_master_emergency_controller_halt_and_resumption(emergency_setup):
    """Verify biometric gating, 5-system sequential freeze, red banner, and per-system un-halt."""
    controller, cascade, playbooks = emergency_setup

    # 1. Low biometric confidence rejected
    res_low = controller.execute_master_emergency_halt("Confirm emergency halt", biometric_confidence=0.88)
    assert res_low["is_halted"] is False
    assert res_low["status"] == "REJECTED"

    # 2. Missing confirmation phrase rejected
    res_no_phrase = controller.execute_master_emergency_halt("Please stop everything now", biometric_confidence=0.98)
    assert res_no_phrase["is_halted"] is False
    assert res_no_phrase["status"] == "REJECTED"

    # 3. High confidence + Valid Phrase executes 5-system halt
    res_ok = controller.execute_master_emergency_halt("Confirm emergency halt", biometric_confidence=0.97)
    assert res_ok["is_halted"] is True
    assert controller.is_emergency_active is True
    assert len(controller.halt_states) == 5
    assert controller.halt_states["trading_bot"].is_halted is True
    assert controller.halt_states["nexus"].is_halted is True
    assert controller.halt_states["forge"].is_halted is True
    assert controller.halt_states["ai_universe"].is_halted is True
    assert controller.halt_states["friday_operators"].is_halted is True

    # 4. Red Banner Text Displayed
    banner = controller.get_emergency_banner()
    assert banner is not None
    assert "EMERGENCY HALT ACTIVE" in banner

    # 5. Bulk Resumption Prohibited
    res_bulk = controller.resume_subsystem("ALL", confirmation_token="auth_9912")
    assert res_bulk["is_resumed"] is False
    assert res_bulk["status"] == "DENIED"

    # 6. Individual Per-System Resumption Allowed
    res_trade = controller.resume_subsystem("trading_bot", confirmation_token="auth_token_trade_01")
    assert res_trade["is_resumed"] is True
    assert controller.halt_states["trading_bot"].is_halted is False
    assert controller.is_emergency_active is True  # Other systems still halted


# =========================================================================
# 2. Cascade Failure Detection & Auto-Isolation Tests
# =========================================================================

def test_cascade_failure_detector_isolation_and_recovery(emergency_setup):
    """Verify upstream fault isolation and data-freshness verified auto-reconnection."""
    controller, cascade, playbooks = emergency_setup

    # 1. Telemetry showing AI-Universe Down (latency 8500ms)
    degraded_telemetry = {
        "ai_universe": {"status": "DOWN", "latency_ms": 8500},
        "forge": {"status": "HEALTHY", "latency_ms": 110},
    }
    events = cascade.evaluate_dependency_health(degraded_telemetry)
    assert len(events) >= 1
    assert events[0]["type"] == "SUBSYSTEM_ISOLATED"
    assert "ai_universe" in cascade.isolated_subsystems

    # 2. Telemetry showing AI-Universe Recovered (latency 95ms)
    healthy_telemetry = {
        "ai_universe": {"status": "HEALTHY", "latency_ms": 95, "data_age_sec": 2.1},
        "forge": {"status": "HEALTHY", "latency_ms": 110},
    }
    recovery_events = cascade.evaluate_dependency_health(healthy_telemetry)
    assert any(e.get("type") == "SUBSYSTEM_RECONNECTED" for e in recovery_events)
    assert "ai_universe" not in cascade.isolated_subsystems


# =========================================================================
# 3. Emergency Playbook System Tests
# =========================================================================

def test_emergency_playbooks_execution(emergency_setup):
    """Verify execution of all 5 automated emergency playbooks with spoken status updates."""
    controller, cascade, playbooks = emergency_setup

    # 1. Trading Loss Spike Playbook
    res_trade = playbooks.run_playbook("Run emergency playbook for trading loss")
    assert res_trade.playbook_id == "PLAYBOOK:trading_loss_spike"
    assert res_trade.is_successful is True
    assert len(res_trade.step_results) == 4
    assert any("Trading bot halt verified" in s.spoken_update for s in res_trade.step_results)

    # 2. Nexus Website Down Playbook
    res_web = playbooks.run_playbook("Run emergency playbook for website down")
    assert res_web.playbook_id == "PLAYBOOK:website_down"
    assert res_web.is_successful is True
    assert res_web.escalation_required is True

    # 3. Forge Runaway Playbook
    res_forge = playbooks.run_playbook("Run emergency playbook for forge runaway")
    assert res_forge.playbook_id == "PLAYBOOK:forge_runaway"
    assert res_forge.is_successful is True
    assert any("disk space freed" in s.spoken_update for s in res_forge.step_results)

    # 4. AI-Universe Outage Playbook
    res_ai = playbooks.run_playbook("Run emergency playbook for ai universe outage")
    assert res_ai.playbook_id == "PLAYBOOK:ai_universe_outage"
    assert res_ai.is_successful is True

    # 5. Security / Data Breach Playbook
    res_breach = playbooks.run_playbook("Run emergency playbook for data breach")
    assert res_breach.playbook_id == "PLAYBOOK:data_breach"
    assert res_breach.is_successful is True
    assert res_breach.escalation_required is True
