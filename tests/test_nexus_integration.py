# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Nexus Website & Growth Integration."""

from datetime import datetime, timezone, timedelta
import pytest

from friday.ecosystem.command_router import EcosystemCommandRouter, SubsystemRoute
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry
from friday.operators.nexus_vigilance_operator import NexusVigilanceOperator
from friday.skills.nexus_operator import NexusOperatorSkill
from friday.skills.registry import skill_registry
from friday.ui.ecosystem_panel import EcosystemDashboardPanel


@pytest.fixture
def nexus_setup():
    skill = NexusOperatorSkill(base_url="http://localhost:8002", mock_mode=True)
    vigilance = NexusVigilanceOperator(skill=skill, poll_interval_sec=60)
    registry = EcosystemRegistry()
    panel = EcosystemDashboardPanel(registry=registry)
    router = EcosystemCommandRouter()
    return skill, vigilance, registry, panel, router


# =========================================================================
# 1. Nexus Operator Skill Core Methods Tests
# =========================================================================

def test_nexus_operator_skill_methods(nexus_setup):
    """Verify all 8 core API methods of NexusOperatorSkill."""
    skill, vigilance, registry, panel, router = nexus_setup

    # 1. get_site_status
    status = skill.get_site_status()
    assert status["status"] == "HEALTHY"
    assert status["visitors_today"] == 4280
    assert status["conversion_rate_pct"] == 3.65

    # 2. get_high_intent_leads
    leads = skill.get_high_intent_leads()
    assert len(leads) >= 2
    assert leads[0]["score"] >= 80
    assert "acme-corp.com" in leads[0]["company_domain"]

    # 3. diagnose_conversion_drop
    diag = skill.diagnose_conversion_drop()
    assert "Mobile Safari" in diag["primary_cause"]
    assert diag["verified_by_nexus_policy"] is True

    # 4. get_pending_incidents
    incidents = skill.get_pending_incidents()
    assert isinstance(incidents, list)

    # 5. start_nexus_workflow
    wf = skill.start_nexus_workflow("optimize_checkout_funnel", {"target_page": "/checkout"})
    assert wf["status"] == "INITIATED"
    assert wf["authorized_by_policy_engine"] is True

    # 6. pause_nexus_experiment
    exp = skill.pause_nexus_experiment("exp_hero_cta_v2")
    assert exp["success"] is True
    assert exp["status"] == "PAUSED"

    # 7. explain_nexus_decision
    expl = skill.explain_nexus_decision("req_101")
    assert "Promote Hero CTA" in expl["decision"]
    assert expl["ai_universe_consultation"]["consensus"] == "UNANIMOUS_PROCEED"

    # 8. run_nexus_health_check
    health = skill.run_nexus_health_check()
    assert health["status"] == "HEALTHY"
    assert health["policy_engine"] == "ACTIVE"


# =========================================================================
# 2. Nexus Voice Commands Tests
# =========================================================================

def test_nexus_voice_commands(nexus_setup):
    """Verify voice command parsing and spoken execution."""
    skill, vigilance, registry, panel, router = nexus_setup

    # 1. Website status
    res_status = skill.execute("Website status")
    assert res_status.success is True
    assert "Website Health Status: HEALTHY" in res_status.output
    assert "4,280 visitors" in res_status.output

    # 2. Any high-intent visitors?
    res_leads = skill.execute("Any high-intent visitors?")
    assert res_leads.success is True
    assert "acme-corp.com" in res_leads.output

    # 3. Why did conversions drop?
    res_diag = skill.execute("Why did conversions drop?")
    assert res_diag.success is True
    assert "Nexus Conversion Diagnosis" in res_diag.output

    # 4. Any website incidents?
    res_inc = skill.execute("Any website incidents?")
    assert res_inc.success is True
    assert "0 active website incidents" in res_inc.output

    # 5. Explain that Nexus decision
    res_expl = skill.execute("Explain that Nexus decision")
    assert res_expl.success is True
    assert "Nexus Decision Audit" in res_expl.output

    # 6. SENSITIVE: Pause the website experiment
    res_pause = skill.execute("Pause the website experiment")
    assert res_pause.success is True
    assert "PAUSED" in res_pause.output


# =========================================================================
# 3. Nexus Vigilance Operator Alerts & Memory Tagging Tests
# =========================================================================

def test_nexus_vigilance_operator_alerts(nexus_setup):
    """Verify 60s lifecycle watchdog, incident alerts, and untrusted memory tagging."""
    skill, vigilance, registry, panel, router = nexus_setup

    # Initial tick (detects initial leads)
    events = vigilance.tick()
    assert len(events) >= 2
    assert all(e["trust_level"] == "UNTRUSTED_EXTERNAL" for e in events)
    assert any(e["type"] == "HIGH_INTENT_LEAD_DETECTED" for e in events)

    # Inject a new incident
    vigilance.inject_simulated_incident({
        "id": "inc_checkout_error",
        "severity": "CRITICAL",
        "title": "Checkout payment gateway timeout",
        "description": "504 Gateway Timeout on Stripe webhook endpoint.",
    })

    # Second tick detects new incident
    events2 = vigilance.tick()
    assert any(e["type"] == "NEW_INCIDENT" for e in events2)
    assert any(e["severity"] == "CRITICAL" for e in events2)


# =========================================================================
# 4. Ecosystem Dashboard, Registry & Command Router Tests
# =========================================================================

def test_nexus_ecosystem_dashboard_and_routing(nexus_setup):
    """Verify Nexus card presentation, registry integration, and router intents."""
    skill, vigilance, registry, panel, router = nexus_setup

    # Panel data
    data = panel.render_panel_data()
    assert "nexus" in data["cards"]
    nexus_card = data["cards"]["nexus"]
    assert nexus_card["title"] == "Nexus Website & Growth"
    assert "98.4/100" in nexus_card["site_health"]
    assert "View high-intent leads" in nexus_card["quick_actions"]

    # Markdown presentation
    md = panel.render_markdown()
    assert "Nexus Website & Growth Card" in md

    # Registry lookup
    sub = registry.get_subsystem("nexus")
    assert sub is not None
    assert sub.category == "growth"
    assert sub.icon == "🌐"

    # Skill Registry
    assert any(s.name == "nexus_operator" for s in skill_registry.list_skills())
    assert skill_registry.get("nexus_operator") is not None

    # Command Router
    route, _ = router.route_command("Website status")
    assert route == SubsystemRoute.NEXUS

    route_leads, _ = router.route_command("Any high-intent visitors today?")
    assert route_leads == SubsystemRoute.NEXUS
