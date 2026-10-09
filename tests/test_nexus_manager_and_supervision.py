"""Comprehensive Test Suite for FRIDAY Nexus Manager & Website Supervision."""

import threading

import pytest

from friday.integrations.nexus_client import NexusCommandClient
from friday.operators.nexus_supervisor import NexusSupervisorOperator
from friday.skills.nexus_manager import NexusManagerSkill
from friday.skills.registry import skill_registry
from tests.mock_nexus_api import MockNexusServer


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
    assert "Website Health Overview: status is HEALTHY" in res1.output
    assert res1.output.endswith("(sample data)")

    # 2. "Who's on my website?"
    res2 = skill.execute("Who's on my website?")
    assert res2.success is True
    assert "Nexus reports 3 active visitors on the site" in res2.output
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
    assert "Nexus reports no active website incidents" in res5.output
    assert res5.output.endswith("(sample data)")

    # 6. "Show the lead pipeline"
    res6 = skill.execute("Show the lead pipeline")
    assert res6.success is True
    assert "Nexus Lead Pipeline by Stage" in res6.output
    assert "Decision" in res6.output

    # 7. "Approve that Nexus action"
    res7 = skill.execute("Approve that Nexus action")
    assert res7.success is True
    assert "Sample action **APPROVED**" in res7.output or "No pending" in res7.output
    assert res7.output.endswith("(sample data)")
    assert "no live Nexus request or deployment was made" in res7.output

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


@pytest.fixture
def live_nexus_manager_server():
    server = MockNexusServer(port=8986)
    server.start()
    yield server
    server.stop()


def test_nexus_manager_executes_live_reads_and_actions_over_http(live_nexus_manager_server):
    """Drive manager methods and spoken tasks through the HTTP client to a local service."""
    skill = NexusManagerSkill(base_url=live_nexus_manager_server.base_url, timeout_sec=1.0)
    assert skill.mock_mode is False

    overview = skill.get_site_overview()
    assert overview["status"] == "DEGRADED"
    assert overview["health_score"] == 71.5
    assert overview["visitors_today"] == 1533
    assert overview["sample_data"] is False

    visitors = skill.get_live_visitors()
    assert visitors[0]["inferred_company"] == "live-prospect.example"
    assert visitors[0]["sample_data"] is False

    pipeline = skill.get_lead_pipeline()
    assert pipeline["DECISION"][0]["lead_id"] == "pipeline_live_1"
    assert pipeline["DECISION"][0]["sample_data"] is False

    incidents = skill.get_incidents()
    assert incidents[0]["id"] == "inc_live_1"
    assert incidents[0]["sample_data"] is False
    approvals = skill.get_pending_approvals()
    assert approvals[0]["action_id"] == "action_live_1"
    assert approvals[0]["sample_data"] is False

    # Execute the user-facing skill entry point, not just internal methods.
    status_voice = skill.execute("Website status")
    assert status_voice.success is True
    assert "71.5/100" in status_voice.output
    assert "1533 visitors" in status_voice.output
    assert "sample data" not in status_voice.output
    visitor_voice = skill.execute("Who's on my website?")
    assert "live-prospect.example" in visitor_voice.output
    assert "sample data" not in visitor_voice.output
    incident_voice = skill.execute("Any website problems?")
    assert "Slow image CDN" in incident_voice.output
    assert "sample data" not in incident_voice.output

    approved = skill.approve_nexus_action("action_live_1")
    assert approved["success"] is True
    assert approved["status"] == "APPROVED"
    assert approved["sample_data"] is False
    assert live_nexus_manager_server.state.approved == ["action_live_1"]

    rejected = skill.reject_nexus_action("action_live_2", "Not supported by evidence")
    assert rejected["success"] is True
    assert rejected["status"] == "REJECTED"
    assert live_nexus_manager_server.state.rejected == [
        {"action_id": "action_live_2", "reason": "Not supported by evidence"}
    ]

    workflow = skill.start_nexus_workflow("review_checkout", {"page": "/checkout"})
    assert workflow["status"] == "QUEUED"
    assert workflow["authorized_by_policy_engine"] is True
    assert live_nexus_manager_server.state.workflows == [
        {"workflow_name": "review_checkout", "params": {"page": "/checkout"}}
    ]

    consultation = skill.get_intelligence_log(limit=1)
    assert consultation[0]["consultation_id"] == "consultation_live_1"
    assert consultation[0]["sample_data"] is False
    strategy = skill.get_strategy_performance()
    assert strategy[0]["strategy_name"] == "Checkout copy test"
    assert strategy[0]["measured_lift_pct"] is None
    assert strategy[0]["sample_data"] is False
    analytics = skill.query_nexus_analytics("What is reported?")
    assert analytics["answer"].startswith("The scripted endpoint")
    assert analytics["sample_data"] is False
    health = skill.run_website_health_check()
    assert health["overall_status"] == "healthy"
    assert health["sample_data"] is False

    commands = [entry["body"]["command"] for entry in live_nexus_manager_server.state.received]
    assert {
        "get_site_overview",
        "get_live_visitors",
        "get_lead_pipeline",
        "get_incidents",
        "get_pending_approvals",
        "approve_action",
        "reject_action",
        "start_workflow",
        "get_intelligence_log",
        "get_strategy_performance",
        "query_analytics",
        "health_check",
    }.issubset(commands)
    assert all(entry["path"] == "/v1/friday/command" for entry in live_nexus_manager_server.state.received)


def test_nexus_manager_distinguishes_empty_from_malformed_or_missing_lists(live_nexus_manager_server):
    """A reported empty list differs from an absent, malformed, or non-JSON reply."""
    server = live_nexus_manager_server
    skill = NexusManagerSkill(base_url=server.base_url, timeout_sec=1.0)

    server.state.response_overrides["get_incidents"] = {"body": {"incidents": []}}
    empty = skill.execute("Any website problems?")
    assert "Nexus reports no active website incidents" in empty.output
    assert "did not answer" not in empty.output

    server.state.response_overrides["get_incidents"] = {"body": {"message": "healthy"}}
    missing = skill.execute("Any website problems?")
    assert "did not answer" in missing.output
    assert "no active website incidents" not in missing.output
    assert "missing list field" in missing.output

    server.state.response_overrides["get_live_visitors"] = {"body": "not-json"}
    malformed = skill.execute("live visitors")
    assert "did not answer" in malformed.output
    assert "no active visitors" not in malformed.output
    assert skill.last_result()["error"] == "Invalid JSON response"

    server.state.response_overrides["get_live_visitors"] = {"body": {"visitors": [None]}}
    wrong_entry_type = skill.execute("live visitors")
    assert "did not answer" in wrong_entry_type.output
    assert "no active visitors" not in wrong_entry_type.output

    server.state.response_overrides.pop("get_live_visitors")
    server.state.fail_with = 503
    unavailable = skill.execute("live visitors")
    assert "did not answer" in unavailable.output
    assert "0 active visitors" not in unavailable.output
    assert skill.last_result()["error"] == "HTTP 503"


def test_nexus_manager_reports_timeout_without_claiming_an_empty_list(live_nexus_manager_server):
    server = live_nexus_manager_server
    server.state.delay_by_command["get_live_visitors"] = 0.15
    skill = NexusManagerSkill(base_url=server.base_url, timeout_sec=0.02)

    result = skill.execute("live visitors")
    assert "did not answer" in result.output
    assert "no active visitors" not in result.output
    assert "timed out" in skill.last_result()["error"].lower()


def test_nexus_manager_does_not_claim_approval_without_confirmation(live_nexus_manager_server):
    server = live_nexus_manager_server
    skill = NexusManagerSkill(base_url=server.base_url, timeout_sec=1.0)

    server.state.response_overrides["approve_action"] = {"body": {}}
    unconfirmed = skill.approve_nexus_action("action_live_1")
    assert unconfirmed["success"] is False
    assert unconfirmed["status"] == "UNCONFIRMED"
    assert "did not confirm" in unconfirmed["message"]
    assert server.state.approved == []

    server.state.response_overrides["approve_action"] = {
        "body": {"action_id": "some_other_action", "status": "APPROVED"}
    }
    wrong_action = skill.approve_nexus_action("action_live_1")
    assert wrong_action["success"] is False
    assert "different action" in wrong_action["message"]


def test_nexus_manager_sample_empty_results_are_still_disclosed(nexus_mgr_setup):
    skill, _ = nexus_mgr_setup
    skill._live_visitors = []
    skill._pipeline_leads = []
    skill._active_incidents = []
    skill._intelligence_log = []
    skill._strategy_learnings = []
    skill._pending_approvals = []

    for request in (
        "live visitors",
        "Any new leads?",
        "Any website problems?",
        "Why did Nexus recommend that?",
        "What has Nexus learned?",
        "Approve that Nexus action",
    ):
        result = skill.execute(request)
        assert result.success is True
        assert result.output.endswith("(sample data)"), (request, result.output)


def test_concurrent_nexus_calls_keep_their_own_results(live_nexus_manager_server):
    """One caller's outage cannot corrupt another call's successfully empty response."""
    server = live_nexus_manager_server
    server.state.response_overrides["get_live_visitors"] = {"body": {"visitors": []}}
    reached_after_read = threading.Event()
    continue_execution = threading.Event()

    class PausedManager(NexusManagerSkill):
        def get_live_visitors(self):
            visitors = super().get_live_visitors()
            reached_after_read.set()
            assert continue_execution.wait(timeout=2)
            return visitors

    skill = PausedManager(base_url=server.base_url, timeout_sec=1.0)
    results = []
    worker = threading.Thread(target=lambda: results.append(skill.execute("live visitors")))
    worker.start()
    assert reached_after_read.wait(timeout=2)

    # Force a distinct failing request in the main thread between the empty
    # response and the first caller's interpretation of that response.
    failed = skill._live("unsupported_command")
    assert failed["ok"] is False
    continue_execution.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].output == "Nexus reports no active visitors right now."


def test_nexus_manager_without_a_service_has_no_site_reading():
    skill = NexusManagerSkill(base_url="http://127.0.0.1:9", timeout_sec=0.05)
    overview = skill.get_site_overview()
    assert overview["available"] is False
    assert overview["status"] == "UNREACHABLE"
    assert "health_score" not in overview
    assert "visitors_today" not in overview
    spoken = skill.execute("Website status")
    assert "Nexus did not answer" in spoken.output
    assert "98.6" not in spoken.output and "5120" not in spoken.output


def test_nexus_manager_approval_voice_does_not_claim_an_unconfirmed_effect(live_nexus_manager_server):
    server = live_nexus_manager_server
    server.state.response_overrides["approve_action"] = {
        "body": {"success": True, "status": "REJECTED", "action_id": "action_live_1"}
    }
    skill = NexusManagerSkill(base_url=server.base_url, timeout_sec=1.0)

    result = skill.execute("Approve that Nexus action")
    assert result.success is False
    assert "did not take effect" in result.output
    assert "Action APPROVED" not in result.output
    assert server.state.approved == []


def test_nexus_transport_does_not_let_payload_replace_the_command(live_nexus_manager_server):
    server = live_nexus_manager_server
    client = NexusCommandClient(base_url=server.base_url, timeout_sec=1.0)

    result = client.command(
        "get_site_overview",
        {"command": "approve_action", "action_id": "action_should_not_be_approved"},
    )

    assert result["ok"] is True
    assert server.state.received[-1]["body"]["command"] == "get_site_overview"
    assert server.state.approved == []
