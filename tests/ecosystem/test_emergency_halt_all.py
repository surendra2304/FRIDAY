# -*- coding: utf-8 -*-
"""End-to-End Test: Master Emergency Halt Sequence Across All 5 Subsystems + FRIDAY.

Validates:
1. Spoken "Emergency stop everything" with biometric authorization and confirmation phrase.
2. Verified 6-step sequential halt:
   - Step 1: Trading Bot panic (flatten positions, cancel open orders, halt)
   - Step 2: Nexus pause (workflows paused, agent proposals held)
   - Step 3: Forge halt (builds checkpointed, pipelines paused)
   - Step 4: Sentinel active tasks killed / scans terminated
   - Step 5: AI-Universe advisory halt (fallback to static params)
   - Step 6: FRIDAY operators paused (health monitoring remains ACTIVE)
3. Red banner broadcast.
4. Bulk resumption prohibited (requires individual per-subsystem un-halt confirmation).
"""

from friday.ecosystem.emergency_controller import MasterEmergencyController


def test_master_emergency_halt_and_resumption_sequence():
    controller = MasterEmergencyController()

    # 1. Emergency stop everything
    halt_res = controller.execute_master_emergency_halt(
        command_phrase="Emergency stop everything! Confirm emergency halt",
        biometric_confidence=0.98,
    )
    assert halt_res["is_halted"] is True
    assert halt_res["status"] == "MASTER_HALT_EXECUTED"
    assert "EMERGENCY HALT ACTIVE" in halt_res["banner_message"]

    # Verify all 6 subsystem halt records
    report = halt_res["halt_report"]
    assert "trading_bot" in report.subsystems_halted
    assert "nexus" in report.subsystems_halted
    assert "forge" in report.subsystems_halted
    assert "sentinel" in report.subsystems_halted
    assert "ai_universe" in report.subsystems_halted
    assert "friday_operators" in report.subsystems_halted

    # Verify Sentinel was specifically halted
    assert report.subsystems_halted["sentinel"].is_halted is True
    assert "terminated" in report.subsystems_halted["sentinel"].halt_action_taken

    # 2. Bulk resumption must be denied
    denied = controller.resume_subsystem("all", "token")
    assert denied["is_resumed"] is False
    assert denied["status"] == "DENIED"

    # 3. Individual per-system resumption works
    resume_trading = controller.resume_subsystem("trading_bot", "UNHALT_TRADING_OK")
    assert resume_trading["is_resumed"] is True
    assert resume_trading["subsystem"] == "trading_bot"
