"""Comprehensive Test Suite for FRIDAY Ecosystem Master Control & FORGE Integration."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.master_dashboard import EcosystemMasterDashboard
from friday.ecosystem.orchestrator import EcosystemOrchestrator, TargetSubsystem
from friday.integrations.forge_auth import ForgeAuthClient
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.forge_monitor import ForgeMonitorOperator
from friday.security.production_security import ProductionSecurityManager
from friday.skills.forge_manager import ForgeManagerSkill
from friday.skills.registry import SkillRegistry
from friday.skills.voice_ecosystem import VoiceEcosystemSkill
from friday.trading.intelligence_engine import IntelligenceEngine


@pytest.fixture
def forge_ecosystem_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    sec_mgr = ProductionSecurityManager()
    auth_client = ForgeAuthClient(rate_limit_per_min=10)

    forge_manager = ForgeManagerSkill(auth_client=auth_client, memory=memory)
    command_center = EcosystemCommandCenter(security_manager=sec_mgr)
    intel_engine = IntelligenceEngine()

    orchestrator = EcosystemOrchestrator(
        command_center=command_center,
        forge_manager=forge_manager,
        intelligence_engine=intel_engine,
    )

    dashboard = EcosystemMasterDashboard(
        command_center=command_center,
        forge_manager=forge_manager,
        intelligence_engine=intel_engine,
    )

    voice_skill = VoiceEcosystemSkill(
        command_center=command_center,
        forge_manager=forge_manager,
        intelligence_engine=intel_engine,
        orchestrator=orchestrator,
    )

    operator = ForgeMonitorOperator(
        forge_manager=forge_manager,
        alert_manager=alert_mgr,
        memory=memory,
    )

    return forge_manager, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr


# =========================================================================
# 1. FORGE Authentication & Rate Limiting Tests
# =========================================================================

def test_forge_auth_client_signing_and_rate_limit(forge_ecosystem_setup):
    """Verify HMAC-SHA256 request signing and token bucket rate limits."""
    forge_mgr, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr = forge_ecosystem_setup

    headers = auth_client.generate_signed_headers("POST", "/api/v1/forge/build", {"goal": "Test Build"})
    assert "X-FRIDAY-Signature" in headers
    assert "X-FRIDAY-Timestamp" in headers
    assert headers["X-FRIDAY-Client-Id"] == "FRIDAY-OS-v2.0"
    assert "Bearer" in headers["Authorization"]

    # Schema validation
    assert auth_client.validate_build_response({"task_id": "t1", "status": "QUEUED"}) is True
    assert auth_client.validate_build_response({"invalid": "payload"}) is False

    # Rate limiting: consume tokens
    for _ in range(10):
        assert auth_client.acquire_rate_limit() is True
    # 11th token should be rejected
    assert auth_client.acquire_rate_limit() is False


# =========================================================================
# 2. FORGE Manager Skill Tests
# =========================================================================

def test_forge_manager_task_lifecycle(forge_ecosystem_setup):
    """Verify task assignment, status polling, artifact retrieval, and cancellation."""
    forge_mgr, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr = forge_ecosystem_setup

    # 1. Assign Task
    tid = forge_mgr.assign_software_task("Build WebSocket L2 Feed Aggregator", priority="HIGH")
    assert "forge_task_" in tid

    # 2. Get Status
    status = forge_mgr.get_task_status(tid)
    assert status["task_id"] == tid
    assert status["status"] in ("READY", "IN_PROGRESS")

    # 3. Artifacts & Review
    artifacts = forge_mgr.get_task_artifacts("forge_task_01")
    assert len(artifacts) >= 2

    review = forge_mgr.review_task_output("forge_task_01")
    assert "FORGE Task Review:" in review
    assert "Test Coverage:" in review

    # 4. Cancel Task
    ok = forge_mgr.cancel_task(tid)
    assert (ok is True or ok.get("cancelled") is True)
    assert forge_mgr.get_task_status(tid)["status"] == "CANCELLED"


# =========================================================================
# 3. Ecosystem Orchestrator Routing & Health Tests
# =========================================================================

def test_ecosystem_orchestrator_routing(forge_ecosystem_setup):
    """Verify intelligent routing across Trading, FORGE, AI-Universe, and Ecosystem."""
    forge_mgr, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr = forge_ecosystem_setup

    assert orchestrator.route_request("Build a cross-exchange arbitrage scanner") == TargetSubsystem.FORGE
    assert orchestrator.route_request("How is my trading position doing?") == TargetSubsystem.TRADING_BOT
    assert orchestrator.route_request("What does AI-Universe predict for BTC?") == TargetSubsystem.AI_UNIVERSE
    assert orchestrator.route_request("Give me the full ecosystem status") == TargetSubsystem.ECOSYSTEM_MASTER

    workflow_res = orchestrator.execute_cross_system_workflow("Build liquidity sniper")
    assert workflow_res["target_subsystem"] == "FORGE"
    assert workflow_res["status"] == "DISPATCHED"

    health = orchestrator.check_system_health()
    assert health["all_systems_healthy"] is True
    assert health["subsystems"]["forge"] == "HEALTHY"


# =========================================================================
# 4. FORGE Monitor Operator & Dashboard Tests
# =========================================================================

def test_forge_monitor_operator_and_master_dashboard(forge_ecosystem_setup):
    """Verify 60s operator alerts and master dashboard rendering."""
    forge_mgr, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr = forge_ecosystem_setup

    # Ticking operator
    events = operator.tick()
    assert isinstance(events, list)
    assert any(e["type"] == "FORGE_TASK_COMPLETED" for e in events)

    # Master Dashboard
    md = dashboard.render_dashboard()
    assert "# 🌐 FRIDAY Unified Ecosystem Master Dashboard" in md
    assert "FORGE Autonomous Software Engineering Engine" in md
    assert "Chronological Cross-System Activity Feed" in md


# =========================================================================
# 5. Voice Ecosystem Skill Commands
# =========================================================================

def test_voice_ecosystem_skill_commands(forge_ecosystem_setup):
    """Verify voice commands across Trading, FORGE, AI-Universe, and Ecosystem."""
    forge_mgr, auth_client, orchestrator, dashboard, voice_skill, operator, alert_mgr = forge_ecosystem_setup

    # Trading voice
    res_trade = voice_skill.execute("Trading status")
    assert res_trade.success is True
    assert "Trading Bot is HEALTHY" in res_trade.output

    # FORGE voice
    res_forge = voice_skill.execute("FORGE status")
    assert res_forge.success is True
    assert "FORGE Software Engineering Engine status:" in res_forge.output

    # AI-Universe voice
    res_ai = voice_skill.execute("AI Universe status")
    assert res_ai.success is True
    assert "AI-Universe Core is HEALTHY" in res_ai.output

    # Ecosystem voice
    res_eco = voice_skill.execute("What's happening?")
    assert res_eco.success is True
    assert "🔵 [TRADING]" in res_eco.output
    assert "🟠 [FORGE]" in res_eco.output


def test_forge_and_voice_ecosystem_registered_in_registry():
    """Verify ForgeManagerSkill and VoiceEcosystemSkill are registered in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    assert reg.get("forge_manager") is not None
    assert reg.get("voice_ecosystem") is not None
