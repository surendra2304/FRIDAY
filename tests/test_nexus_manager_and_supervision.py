"""Comprehensive Test Suite for FRIDAY Nexus Manager & Website Supervision."""

import pytest

from friday.operators.nexus_supervisor import NexusSupervisorOperator
from friday.skills.nexus_manager import NexusManagerSkill
from friday.skills.registry import skill_registry


@pytest.fixture
def nexus_mgr_setup():
    skill = NexusManagerSkill(base_url="http://localhost:8002", mock_mode=True)
    supervisor = NexusSupervisorOperator(skill=skill, poll_interval_sec=30.0)
    return skill, supervisor


# =========================================================================
# 1. Nexus Manager Skill Core Methods Tests
# =========================================================================

def test_nexus_manager_api_methods(nexus_mgr_setup):
    """Verify all 10 core API methods of NexusManagerSkill."""
    skill, supervisor = nexus_mgr_setup

    # 1. get_site_overview
    ov = skill.get_site_overview()
    assert ov["health_score"] >= 90.0
    assert ov["visitors_today"] == 5120
    assert ov["conversion_rate_today"] == 3.82
    assert ov["trust_level"] == "UNTRUSTED_EXTERNAL"

    # 2. get_live_visitors
    visitors = skill.get_live_visitors()
    assert len(visitors) >= 3
    assert any(v["intent_score"] >= 0.8 for v in visitors)
    assert any("acme-corp.com" == v["inferred_company"] for v in visitors)
    assert all(v["trust_level"] == "UNTRUSTED_EXTERNAL" for v in visitors)

    # 3. get_lead_pipeline
    pipeline = skill.get_lead_pipeline()
    assert "DECISION" in pipeline
    assert "EVALUATION" in pipeline
    assert "DISCOVERY" in pipeline
    assert "CLOSED_WON" in pipeline
    assert len(pipeline["DECISION"]) >= 1
    assert pipeline["DECISION"][0]["company_domain"] == "acme-corp.com"

    # 4. get_incidents
    incidents = skill.get_incidents()
    assert isinstance(incidents, list)

    # 5. get_pending_approvals
    approvals = skill.get_pending_approvals()
    assert len(approvals) >= 1
    assert approvals[0]["expected_lift_pct"] > 0
    assert "evidence" in approvals[0]

    # 6. approve_nexus_action
    app_res = skill.approve_nexus_action("act_hero_contrast_v3")
    assert app_res["success"] is True
    assert app_res["status"] == "APPROVED"

    # 7. reject_nexus_action
    rej_res = skill.reject_nexus_action("act_non_existent", reason="Out of scope")
    assert rej_res["status"] in ("REJECTED", "NOT_FOUND")

    # 8. start_nexus_workflow
    wf = skill.start_nexus_workflow("lead_nurture_sequence", {"tier": "Enterprise"})
    assert wf["status"] == "INITIATED"
    assert wf["authorized_by_policy_engine"] is True

    # 9. get_intelligence_log & get_strategy_performance
    intel = skill.get_intelligence_log(limit=2)
    assert len(intel) >= 1
    assert "reasoning_chain" in intel[0]

    strat = skill.get_strategy_performance()
    assert len(strat) >= 3
    assert any(s["status"] == "PROMOTED_TO_PRODUCTION" for s in strat)

    # 10. query_nexus_analytics & run_website_health_check
    analytics = skill.query_nexus_analytics("What is the bounce rate?")
    assert "bounce rate" in analytics["answer"]

    health = skill.run_website_health_check()
    assert health["overall_status"] == "HEALTHY"
    assert health["policy_guardrails"] == "ENFORCING"


# =========================================================================
# 2. Nexus Manager Voice Commands Tests
# =========================================================================

def test_nexus_manager_voice_commands(nexus_mgr_setup):
    """Verify voice command parsing and spoken responses across all 10 phrases."""
    skill, supervisor = nexus_mgr_setup

    # 1. "Website status"
    res1 = skill.execute("Website status")
    assert res1.success is True
    assert "Website Health Overview: Status is HEALTHY" in res1.output

    # 2. "Who's on my website?"
    res2 = skill.execute("Who's on my website?")
    assert res2.success is True
    assert "active visitors on your site" in res2.output
    assert "acme-corp.com" in res2.output

    # 3. "Any new leads?"
    res3 = skill.execute("Any new leads?")
    assert res3.success is True
    assert "acme-corp.com" in res3.output

    # 4. "What's my conversion rate?"
    res4 = skill.execute("What's my conversion rate?")
    assert res4.success is True
    assert "3.82%" in res4.output

    # 5. "Any website problems?"
    res5 = skill.execute("Any website problems?")
    assert res5.success is True
    assert "Nominal operations" in res5.output

    # 6. "Show the lead pipeline"
    res6 = skill.execute("Show the lead pipeline")
    assert res6.success is True
    assert "Nexus Lead Pipeline by Stage" in res6.output
    assert "Decision" in res6.output

    # 7. "Approve that Nexus action"
    res7 = skill.execute("Approve that Nexus action")
    assert res7.success is True
    assert "Action Approved" in res7.output or "No pending" in res7.output

    # 8. "Why did Nexus recommend that?"
    res8 = skill.execute("Why did Nexus recommend that?")
    assert res8.success is True
    assert "Reasoning Chain" in res8.output

    # 9. "What has Nexus learned?"
    res9 = skill.execute("What has Nexus learned?")
    assert res9.success is True
    assert "Nexus Growth Strategy Learnings" in res9.output

    # 10. "Run website health check"
    res10 = skill.execute("Run website health check")
    assert res10.success is True
    assert "Website Operational Audit" in res10.output


# =========================================================================
# 3. Nexus Supervisor Operator Polling & Alerting Tests
# =========================================================================

def test_nexus_supervisor_operator_alerts(nexus_mgr_setup):
    """Verify 30s supervisor lifecycle, incident voice alerts, lead detection, and anomaly offers."""
    skill, supervisor = nexus_mgr_setup

    # Initial tick (detects high-intent leads > 0.8)
    events = supervisor.tick()
    assert len(events) >= 1
    assert any(e["type"] == "HIGH_INTENT_LEAD" for e in events)
    assert all(e["trust_level"] == "UNTRUSTED_EXTERNAL" for e in events)

    # 1. Alert on New Incident (Voice Alert with Severity)
    supervisor.inject_incident({
        "id": "inc_gateway_504",
        "severity": "CRITICAL",
        "title": "API Gateway 504 Gateway Timeout on checkout",
        "description": "Upstream microservice timeout.",
    })
    events_inc = supervisor.tick()
    assert any(e["type"] == "NEW_INCIDENT" for e in events_inc)
    assert any("Attention: New website incident [CRITICAL]" in e.get("voice_alert", "") for e in events_inc)

    # 2. Alert on Conversion Anomaly (> 15% drop)
    supervisor.set_conversion_rate(2.80)  # ~26.7% drop from 3.82 baseline
    events_anom = supervisor.tick()
    assert any(e["type"] == "CONVERSION_ANOMALY_DETECTED" for e in events_anom)
    anom_evt = next(e for e in events_anom if e["type"] == "CONVERSION_ANOMALY_DETECTED")
    assert "Would you like me to run an autonomous diagnosis?" in anom_evt["voice_alert"]

    # 3. Skill Registry loads NexusManagerSkill
    assert skill_registry.get("nexus_manager") is not None
    assert any(s.name == "nexus_manager" for s in skill_registry.list_skills())
