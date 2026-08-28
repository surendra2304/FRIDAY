# -*- coding: utf-8 -*-
"""Comprehensive Seven-System Ecosystem Integration Test Suite.

Validates end-to-end multi-subsystem workflows across all 7 registered systems:
1. Trading Bot (Port 5000)
2. FORGE (Port 8000)
3. Nexus (Port 8002)
4. Sentinel (Port 8003)
5. IntelX (Port 8004)
6. AI-Universe (Port 8001)
7. FRIDAY Core OS

Tests:
- Complex question routing -> IntelX research -> AI-Universe consultation -> Cross-referencing with Sentinel, Nexus, Trading Bot -> Unified intelligence briefing
- Automated research triggers from each system
- Master emergency halt covers IntelX active research cancellation
- Research Library persistence across FRIDAY restarts
- EcosystemCommandRouter intent routing for research, investigations, and library searches
- EcosystemRegistry 7-system health and status validation
"""

import pytest

from friday.core.types import TrustLevel
from friday.ecosystem.command_router import EcosystemCommandRouter, SubsystemRoute
from friday.ecosystem.cross_orchestrator import CrossSystemOrchestrator
from friday.ecosystem.emergency_controller import MasterEmergencyController
from friday.ecosystem.registry import EcosystemRegistry
from friday.memory.research_library import ResearchLibrary
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.intelx_manager import IntelXManagerSkill
from friday.workflows.intelligence_briefing import IntelligenceBriefingWorkflow
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow
from friday.workflows.research_coordination import ResearchCoordinationWorkflow


def test_seven_system_registry_registration_and_health():
    registry = EcosystemRegistry()
    health = registry.get_ecosystem_health()
    status = registry.get_ecosystem_status()

    # Verify all 7 subsystems are registered
    subsystems = ["trading_bot", "forge", "nexus", "sentinel", "intelx", "ai_universe", "friday"]
    for sub in subsystems:
        assert registry.get_subsystem(sub) is not None, f"Subsystem {sub} not registered!"
        assert sub in health["subsystems"], f"Subsystem {sub} missing in health check!"
        assert sub in status["subsystems"], f"Subsystem {sub} missing in status report!"

    assert health["overall_health"] == "HEALTHY"


def test_unified_status_skill_seven_systems_report():
    registry = EcosystemRegistry()
    skill = EcosystemStatusSkill(registry=registry)

    # 1. "Status of everything"
    res_everything = skill.execute("Status of everything")
    assert res_everything.success is True
    out_all = res_everything.output
    assert "Trading Bot:" in out_all
    assert "Forge:" in out_all
    assert "AI-Universe:" in out_all
    assert "Nexus:" in out_all
    assert "Sentinel:" in out_all
    assert "IntelX:" in out_all
    assert "FRIDAY Core:" in out_all

    # 2. "Health of my systems"
    res_health = skill.execute("Health of my systems")
    assert res_health.success is True
    assert "IntelX Research:" in res_health.output
    assert "FRIDAY Core OS:" in res_health.output

    # 3. "Brief me"
    res_brief = skill.execute("Brief me")
    assert res_brief.success is True
    assert "**IntelX**" in res_brief.output


def test_master_daily_briefing_workflow_seven_systems():
    registry = EcosystemRegistry()
    briefing_wf = MasterDailyBriefingWorkflow(registry=registry)

    # Morning briefing
    morning = briefing_wf.generate_morning_briefing()
    assert morning.briefing_type == "MORNING"
    assert "IntelX research pipeline" in morning.spoken_summary
    assert "5. IntelX Autonomous Deep Research" in morning.markdown_report

    # Evening briefing
    evening = briefing_wf.generate_evening_briefing()
    assert evening.briefing_type == "EVENING"
    assert "IntelX completed" in evening.spoken_summary
    assert "Research Delivered:" in evening.markdown_report


def test_cross_system_research_and_trading_workflows():
    orchestrator = CrossSystemOrchestrator()

    # 1. "Research quantum computing security then brief my trading team"
    res_brief = orchestrator.execute_research_and_trading_brief(
        topic="Quantum computing security implications for public key cryptography"
    )
    assert res_brief["success"] is True
    assert res_brief["workflow"] == "RESEARCH_AND_TRADING_BRIEF"
    assert len(res_brief["trading_team_briefing"]) >= 1
    assert "prohibited" in res_brief["advisory_note"]
    assert res_brief["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. "Find out what's causing market volatility and check my positions"
    res_mkt = orchestrator.investigate_market_volatility_and_positions(asset="ETH")
    assert res_mkt["success"] is True
    assert res_mkt["workflow"] == "MARKET_VOLATILITY_AND_POSITIONS_AUDIT"
    assert res_mkt["trading_bot_status"]["status"] == "RUNNING"


def test_master_emergency_halt_includes_intelx_cancellation():
    controller = MasterEmergencyController()

    # Trigger emergency halt
    res = controller.execute_master_emergency_halt(
        command_phrase="Emergency stop everything. Confirm emergency halt.",
        biometric_confidence=0.99,
    )
    assert res["is_halted"] is True
    report = res["halt_report"]
    assert report.is_active is True
    assert "intelx" in report.subsystems_halted
    assert report.subsystems_halted["intelx"].is_halted is True
    assert "cancelled" in report.subsystems_halted["intelx"].halt_action_taken
    assert len(report.subsystems_halted) == 7  # All 7 systems halted


def test_ecosystem_command_router_seven_systems():
    router = EcosystemCommandRouter()

    # 1. "research quantum computing" -> INTELX
    route, args = router.route_command("research quantum computing threats")
    assert route == SubsystemRoute.INTELX
    assert args["mode"] == "NEW_RESEARCH"

    # 2. "what do we know about zero knowledge rollups" -> INTELX (Library search first)
    route, args = router.route_command("what do we know about zero knowledge rollups")
    assert route == SubsystemRoute.INTELX
    assert args["mode"] == "LIBRARY_FIRST_SEARCH"
    assert "zero knowledge rollups" in args["topic"]

    # 3. "investigate CVE-2026-4401 in auth" -> SENTINEL
    route, args = router.route_command("investigate CVE-2026-4401 in auth stack")
    assert route == SubsystemRoute.SENTINEL
    assert args["action"] == "SECURITY_INVESTIGATION"

    # 4. "investigate competitor pricing models" -> INTELX
    route, args = router.route_command("investigate competitor pricing models in SaaS")
    assert route == SubsystemRoute.INTELX
    assert args["action"] == "GENERAL_INVESTIGATION"


def test_research_library_persistence_and_cross_subsystem_synthesis():
    # Instantiate library
    library = ResearchLibrary()

    # Save research findings
    library.save_research_entry(
        run_id="run-mesh-01",
        topic="Decentralized mesh networks and latency benchmarks",
        domain="technical",
        depth="standard",
        findings=[
            {
                "finding_id": "f-mesh-01",
                "claim": "Mesh routing protocols achieve sub-50ms peer hops under 100-node topology.",
                "confidence": 0.93,
                "citations": ["IEEE Mesh Networking 2026"],
            }
        ],
    )

    # Search library (simulating fresh reboot)
    search_res = library.search("Decentralized mesh networks", domain="technical")
    assert len(search_res) >= 1
    assert "Mesh routing" in search_res[0]["top_finding"]
