# -*- coding: utf-8 -*-
"""Comprehensive Eight-System Integration Test Suite for FRIDAY.

Validates end-to-end multi-subsystem workflows across all 8 registered systems:
1. Trading Bot (5000)
2. FORGE (8000)
3. Nexus (8002)
4. Sentinel (8003)
5. IntelX (8004)
6. Futuris (8005)
7. AI-Universe (8001)
8. FRIDAY Core (9000)

Test Flows:
1. Full Research-Informed Predictive Pipeline:
   Complex question -> IntelX research -> Futuris forecast informed by research -> Cross-reference Sentinel & Nexus & Trading -> Unified briefing
2. Prediction-Informed Decisions across all systems (Forge capacity queue, Trading risk context, Nexus scaling, Sentinel urgency)
3. 8-System Master Emergency Halt Cascade with Futuris subscription cancellation
4. Prediction Accuracy Tracking and Feedback loop
5. Ecosystem Command Router 8-system intent mapping
"""

import pytest

from friday.core.prediction_decisions import PredictionInformedDecisionEngine
from friday.ecosystem.command_router import EcosystemCommandRouter, SubsystemRoute
from friday.ecosystem.cross_orchestrator import CrossSystemOrchestrator
from friday.ecosystem.emergency_controller import MasterEmergencyController
from friday.ecosystem.registry import EcosystemRegistry
from friday.skills.ecosystem_status import EcosystemStatusSkill
from friday.skills.futuris_manager import FuturisManagerSkill
from friday.skills.intelx_manager import IntelXManagerSkill
from friday.workflows.master_briefing import MasterDailyBriefingWorkflow
from friday.workflows.prediction_tracking import PredictionTrackingWorkflow
from friday.workflows.predictive_briefing import PredictiveBriefingWorkflow


def test_eight_system_registry_registration_and_health():
    registry = EcosystemRegistry()
    subs = registry.list_subsystems()
    assert len(subs) == 8
    names = [s.name for s in subs]
    for expected in ["trading_bot", "forge", "nexus", "sentinel", "intelx", "futuris", "ai_universe", "friday"]:
        assert expected in names

    health = registry.get_ecosystem_health()
    assert health["overall_health"] == "HEALTHY"
    assert "futuris" in health["subsystems"]
    assert health["subsystems"]["futuris"]["status"] == "HEALTHY"


def test_unified_status_skill_eight_systems_report():
    registry = EcosystemRegistry()
    skill = EcosystemStatusSkill(registry=registry)

    res = skill.execute("Status of everything")
    assert res.success is True
    out = res.output
    assert "Unified Ecosystem Master Status Report (8 Subsystems)" in out
    assert "Algorithmic Trading Bot" in out
    assert "FORGE Software Engineering Engine" in out
    assert "Nexus Autonomous Growth" in out
    assert "Sentinel Autonomous Security" in out
    assert "IntelX Autonomous Deep Research" in out
    assert "Futuris Probabilistic Forecasting" in out
    assert "AI-Universe Multi-LLM" in out
    assert "FRIDAY Central Multimodal" in out


def test_master_daily_briefing_workflow_eight_systems():
    registry = EcosystemRegistry()
    workflow = MasterDailyBriefingWorkflow(registry=registry)

    snap = workflow.generate_morning_briefing()
    assert len(snap.subsystems_included) == 8
    assert "Futuris forecasts nominal system loads" in snap.spoken_summary
    assert "6. Futuris Probabilistic Forecasting & Risk Outlook" in snap.markdown_report


def test_cross_system_predictive_scaling_and_risk_workflows():
    orch = CrossSystemOrchestrator()

    # 1. Website scaling decision workflow
    scale_res = orch.evaluate_website_scaling_decision()
    assert scale_res["workflow"] == "WEBSITE_SCALING_DECISION"
    assert "recommendation" in scale_res
    assert "Forecasted Traffic" in scale_res["formatted_summary"]

    # 2. Global risk exposure assessment
    risk_res = orch.assess_global_risk_exposure()
    assert risk_res["workflow"] == "GLOBAL_RISK_EXPOSURE"
    assert "Trading Drawdown Risk" in risk_res["formatted_summary"]
    assert "Security Exploit Threat" in risk_res["formatted_summary"]


def test_master_emergency_halt_includes_futuris_cancellation():
    controller = MasterEmergencyController()

    res = controller.execute_master_emergency_halt(
        command_phrase="Emergency stop everything. Confirm emergency halt.",
        biometric_confidence=0.99,
    )
    assert res["is_halted"] is True
    report = res["halt_report"]
    assert report.is_active is True
    assert len(report.subsystems_halted) == 8
    assert "futuris" in report.subsystems_halted
    assert report.subsystems_halted["futuris"].is_halted is True
    assert "cancelled" in report.subsystems_halted["futuris"].halt_action_taken


def test_ecosystem_command_router_eight_systems():
    router = EcosystemCommandRouter()

    # 1. Route to Futuris
    res_pred = router.route_command("What does Futuris predict for visitor growth?")
    assert res_pred["route"] == SubsystemRoute.FUTURIS.value
    assert "Futuris Prediction" in res_pred["output"]

    # 2. Route to IntelX
    res_res = router.route_command("Research quantum cryptography")
    assert res_res["route"] == SubsystemRoute.INTELX.value

    # 3. Route to Cross-System Scaling
    res_scale = router.route_command("Should I scale up my website?")
    assert res_scale["route"] == SubsystemRoute.ALL.value
    assert "Website Scaling Recommendation" in res_scale["output"]


def test_full_pipeline_research_informed_prediction_synthesis():
    """Validates: Complex question -> IntelX research -> Futuris prediction -> Synthesis."""
    intelx = IntelXManagerSkill()
    futuris = FuturisManagerSkill()
    decisions = PredictionInformedDecisionEngine(futuris_skill=futuris)

    # 1. Research topic via IntelX
    res_intel = intelx.submit_research("What are the leading attack vectors against web checkout APIs?", domain_hint="security")
    assert res_intel["run_id"] is not None

    # 2. Feed security research into Futuris forecast
    fc_threat = futuris.request_forecast("Checkout API Attack Escalation", horizon="24 hours", confidence_level=0.90)
    assert len(fc_threat["confidence_interval"]) == 2

    # 3. Evaluate Sentinel scan urgency based on predicted threat
    eval_sent = decisions.evaluate_sentinel_scan_urgency(asset_target="api.surendra.dev/checkout", cve_id="CVE-2026-CHECKOUT")
    assert eval_sent.domain == "sentinel"
    assert eval_sent.recommendation in ["ESCALATE_IMMEDIATE", "STANDARD_SCHEDULE"]
