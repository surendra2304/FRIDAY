"""Comprehensive Test Suite for FRIDAY Nexus Website & Growth Integration."""

import pytest

from friday.ecosystem.command_router import EcosystemCommandRouter, SubsystemRoute
from friday.ecosystem.registry import EcosystemRegistry
from friday.operators.nexus_vigilance_operator import NexusVigilanceOperator
from friday.skills.nexus_operator import NexusOperatorSkill
from friday.skills.registry import skill_registry
from friday.ui.ecosystem_panel import EcosystemDashboardPanel
from tests.mock_nexus_api import MockNexusServer


@pytest.fixture
def nexus_setup():
    skill = NexusOperatorSkill(base_url="http://localhost:8002", mock_mode=True)
    vigilance = NexusVigilanceOperator(skill=skill, poll_interval_sec=60)
    registry = EcosystemRegistry()
    # Wire the registry to the operator. Left alone, the registry answers
    # "UNVERIFIED" for every subsystem (which is why the panel used to print a
    # literal 98.4/100 instead); wired up, the panel displays what the Nexus
    # skill actually reports and the assertions below are statements about it.
    nexus_entry = registry.get_subsystem("nexus")
    assert nexus_entry is not None
    nexus_entry.status_callable = skill.get_site_status
    nexus_entry.health_check_callable = skill.run_nexus_health_check
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

    # 1. Website status. The fixture runs the operator in mock mode, so every
    # sample figure is tagged as such rather than passed off as a live reading.
    res_status = skill.execute("Website status")
    assert res_status.success is True
    assert "Website Health Status: HEALTHY" in res_status.output
    assert "4280 visitors" in res_status.output
    assert res_status.output.endswith("(sample data)")

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
    assert "Nexus reports no active website incidents" in res_inc.output

    # 5. Explain that Nexus decision
    res_expl = skill.execute("Explain that Nexus decision")
    assert res_expl.success is True
    assert "Nexus Decision Audit" in res_expl.output

    # 6. SENSITIVE: Pause the website experiment
    res_pause = skill.execute("Pause the website experiment")
    assert res_pause.success is True
    assert "PAUSED" in res_pause.output

    # 7. An operator with no Nexus behind it reports the absence, not the sample.
    live = NexusOperatorSkill(base_url="http://127.0.0.1:9")
    out = live.execute("Website status").output
    assert "did not answer" in out
    assert "98.4" not in out and "4280" not in out


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

    # Panel data - sourced from the wired-up operator, not from a literal.
    data = panel.render_panel_data()
    assert "nexus" in data["cards"]
    nexus_card = data["cards"]["nexus"]
    assert nexus_card["title"] == "Nexus Website & Growth"
    reported = skill.get_site_status()
    assert nexus_card["site_health"] == f"{reported['health_score']:.1f}/100"
    assert nexus_card["visitors_today"] == f"{reported['visitors_today']:,.0f} visitors"
    assert "View high-intent leads" in nexus_card["quick_actions"]

    # And an unwired panel reports the absence of a reading rather than a number.
    unwired_card = EcosystemDashboardPanel(registry=EcosystemRegistry()).render_panel_data()["cards"]["nexus"]
    assert unwired_card["site_health"] == "unknown (no reading)"
    assert unwired_card["visitors_today"] == "unknown (no reading)"

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


# =========================================================================
# 5. Live bridge: the operator against a real HTTP Nexus endpoint
# =========================================================================

@pytest.fixture
def live_nexus():
    server = MockNexusServer(port=8984)
    server.start()
    yield server
    server.stop()


def test_nexus_operator_reads_the_live_endpoint(live_nexus):
    """Every reading comes from the endpoint, and the request that fetched it is on record."""
    skill = NexusOperatorSkill(base_url=live_nexus.base_url)

    status = skill.get_site_status()
    assert status["status"] == "DEGRADED"
    assert status["health_score"] == 71.5
    assert status["visitors_today"] == 1533
    assert status["sample_data"] is False
    assert live_nexus.state.received[-1]["body"]["command"] == "get_site_status"

    leads = skill.get_high_intent_leads()
    assert [lead["company_domain"] for lead in leads] == ["live-prospect.example"]

    incidents = skill.get_pending_incidents()
    assert incidents[0]["severity"] == "MINOR"

    diag = skill.diagnose_conversion_drop()
    assert diag["primary_cause"] == "Checkout JS bundle regression"
    assert diag["sample_data"] is False

    pause = skill.pause_nexus_experiment("exp_live_1")
    assert pause["success"] is True
    assert live_nexus.state.paused == ["exp_live_1"]

    health = skill.run_nexus_health_check()
    assert health["status"] == "healthy"
    assert health["policy_engine"] == "ACTIVE"

    # The voice layer reads the same replies, with no sample figures anywhere.
    voice = skill.execute("Website status").output
    assert "71.5/100" in voice
    assert "1533 visitors" in voice
    assert "sample data" not in voice


def test_nexus_operator_reports_unreachable_without_inventing_data(live_nexus):
    """With Nexus down, nothing is reported as if it had answered."""
    skill = NexusOperatorSkill(base_url=live_nexus.base_url)
    live_nexus.state.fail_with = 503

    status = skill.get_site_status()
    assert status["available"] is False
    assert status["status"] == "UNREACHABLE"
    assert status["error"] == "HTTP 503"
    assert "health_score" not in status

    assert skill.get_high_intent_leads() == []
    assert skill.get_pending_incidents() == []

    # The failure is distinguishable from "Nexus says there are none".
    voice = skill.execute("Any high-intent visitors?").output
    assert "did not answer" in voice
    assert "0 high-intent" not in voice

    health = skill.run_nexus_health_check()
    assert health["status"] == "UNREACHABLE"
    assert health["error"] == "HTTP 503"


def test_unwired_registry_and_vigilance_report_unknown_not_sample_data():
    """The default registry entry and the default vigilance operator make no claims."""
    registry = EcosystemRegistry()
    entry = registry.get_subsystem("nexus")
    assert entry is not None
    reported = entry.status_callable()
    assert reported["status"] == "UNVERIFIED"

    default_skill = NexusOperatorSkill()
    assert default_skill.get_site_status()["status"] == "UNREACHABLE"
    assert default_skill.get_site_status()["sample_data"] is False


def test_vigilance_treats_a_silent_nexus_as_an_outage(live_nexus):
    """A skill that never answered is not a successful poll, and escalates."""
    from datetime import datetime, timedelta, timezone

    skill = NexusOperatorSkill(base_url=live_nexus.base_url)
    live_nexus.state.fail_with = 503
    vigilance = NexusVigilanceOperator(skill=skill, poll_interval_sec=1)

    assert vigilance.tick() == []
    state = vigilance.vigilance_state
    assert state.last_successful_poll is None, "a failed poll was recorded as successful"
    assert state.unreachable_since is not None

    # Still inside the 2-minute window: recorded, not yet escalated.
    assert vigilance.tick() == []
    assert not any(e["type"] == "SERVICE_UNREACHABLE_CRITICAL" for e in vigilance.get_recent_events())

    # Pretend the outage has lasted longer than the threshold.
    state.unreachable_since = datetime.now(timezone.utc) - timedelta(minutes=3)
    events = vigilance.tick()
    assert any(e["type"] == "SERVICE_UNREACHABLE_CRITICAL" for e in events)

    # Once Nexus answers again the clock is cleared and incidents/leads flow.
    live_nexus.state.fail_with = None
    vigilance.tick()
    assert state.unreachable_since is None
    assert state.last_successful_poll is not None
