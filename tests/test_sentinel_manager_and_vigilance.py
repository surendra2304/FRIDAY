"""Comprehensive Test Suite for Sentinel Security Integration.

Validates:
1. SentinelManagerSkill API methods.
2. Voice command routing & execution.
3. SentinelVigilanceOperator 60s polling cycle and alerts.
4. Trust boundary invariant: All data tagged TrustLevel.UNTRUSTED_EXTERNAL.
"""

from datetime import datetime, timedelta, timezone

from friday.core.types import TrustLevel
from friday.operators.sentinel_vigilance_operator import SentinelVigilanceOperator
from friday.skills.sentinel_manager import (
    SecurityFinding,
    SentinelManagerSkill,
    SentinelPendingAction,
)


def test_sentinel_manager_api_methods():
    skill = SentinelManagerSkill(default_target_domain="mywebsite.com")

    # 1. Health check
    health = skill.get_sentinel_health()
    assert health["status"] == "HEALTHY"
    assert health["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Submit security task (delegate)
    res = skill.submit_security_task(target="mywebsite.com", mode="full_web")
    assert res["success"] is True
    assert res["mode"] == "full_web"
    assert res["phase"] == "RECON"
    assert res["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value
    task_id = res["task_id"]

    # 3. Get task status
    status = skill.get_task_status(task_id)
    assert status["success"] is True
    assert status["phase"] == "RECON"
    assert status["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 4. Get findings
    findings = skill.get_findings()
    assert len(findings) >= 2
    assert findings[0]["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 5. Get report
    report = skill.get_report(report_type="executive")
    assert report["success"] is True
    assert "voice_summary" in report
    assert report["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 6. Attack surface graph
    surface = skill.get_attack_surface()
    assert surface["success"] is True
    assert len(surface["nodes"]) > 0
    assert len(surface["edges"]) > 0
    assert len(surface["choke_points"]) > 0
    assert surface["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 7. Audit trail
    trail = skill.get_audit_trail()
    assert trail["success"] is True
    assert trail["verification_status"] == "VALID"
    assert "audit_signature" in trail
    assert trail["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 8. Scheduled assessments
    schedules = skill.list_scheduled_assessments()
    assert len(schedules) >= 1

    sched_res = skill.create_scheduled_assessment(target="mywebsite.com", frequency="daily", mode="api_security")
    assert sched_res["success"] is True
    assert sched_res["frequency"] == "daily"
    assert sched_res["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value


def test_sentinel_manager_approvals_workflow():
    skill = SentinelManagerSkill()
    action = SentinelPendingAction(
        action_id="act-99",
        task_id="sec-task-101",
        action_name="Blind SQL Injection Dynamic Verification",
        target="https://example.com/api/checkout",
        impact_level="HIGH_IMPACT",
        evidence="Observed 5.2s database sleep response on payload injection.",
        rationale="Verify vulnerability without destructive write operations.",
        status="PENDING",
    )
    skill._pending_actions[action.action_id] = action

    # Test approve
    app_res = skill.approve_action("act-99")
    assert app_res["success"] is True
    assert app_res["status"] == "APPROVED"
    assert skill._pending_actions["act-99"].status == "APPROVED"

    # Test reject on new action
    action2 = SentinelPendingAction(
        action_id="act-100",
        task_id="sec-task-101",
        action_name="Aggressive Stress Probe",
        target="https://example.com/api/test",
        impact_level="HIGH_IMPACT",
        evidence="High concurrency probe requested.",
        rationale="Check concurrency lock limits.",
        status="PENDING",
    )
    skill._pending_actions[action2.action_id] = action2
    rej_res = skill.reject_action("act-100", reason="Do not run stress probe in business hours")
    assert rej_res["success"] is True
    assert rej_res["status"] == "REJECTED"


def test_sentinel_manager_voice_commands():
    skill = SentinelManagerSkill(default_target_domain="mywebsite.com")

    # 1. "Run a security scan on my website"
    res1 = skill.execute("Run a security scan on my website")
    assert res1.success is True
    assert "Security scan initiated" in res1.output
    assert "Passive Recon Task" in res1.output

    # 2. "Security status"
    res2 = skill.execute("Security status")
    assert res2.success is True
    assert "Sentinel Security Status" in res2.output

    # 3. "What did the security scan find?"
    res3 = skill.execute("What did the security scan find?")
    assert res3.success is True
    assert "Sentinel Security Findings" in res3.output

    # 4. "Show me the attack surface"
    res4 = skill.execute("Show me the attack surface")
    assert res4.success is True
    assert "Discovered Attack Surface" in res4.output
    assert "Perimeter Nodes" in res4.output

    # 5. "Approve that security action"
    action = SentinelPendingAction(
        action_id="act-auth-1",
        task_id="sec-task-101",
        action_name="Verify Remote File Inclusion payload",
        target="https://mywebsite.com/docs",
        impact_level="HIGH_IMPACT",
        evidence="Path traversal pattern detected in doc viewer query parameter.",
        rationale="Confirm read access boundary.",
        status="PENDING",
    )
    skill._pending_actions[action.action_id] = action
    res5 = skill.execute("Approve that security action")
    assert res5.success is True
    assert "Security Action Approved" in res5.output

    # 6. "Generate security report"
    res6 = skill.execute("Generate security report")
    assert res6.success is True
    assert "Executive Security Report Generated" in res6.output

    # 7. "Schedule weekly security scans"
    res7 = skill.execute("Schedule weekly security scans")
    assert res7.success is True
    assert "Recurring Security Assessment Scheduled" in res7.output

    # 8. "Check for new vulnerabilities"
    res8 = skill.execute("Check for new vulnerabilities")
    assert res8.success is True
    assert "Vulnerability Assessment Triggered" in res8.output


def test_sentinel_vigilance_operator_alerts():
    skill = SentinelManagerSkill(default_target_domain="mywebsite.com")
    operator = SentinelVigilanceOperator(skill=skill, poll_interval_sec=60.0)

    # Initial cycle - discovers baseline findings
    operator.run_cycle()

    # 1. Inject new CRITICAL finding
    crit_finding = SecurityFinding(
        finding_id="f-crit-01",
        title="SQL injection in checkout endpoint",
        severity="CRITICAL",
        target_asset="https://mywebsite.com/checkout",
        description="Unsanitized order_id parameter allows arbitrary query execution.",
        cve_or_cwe="CWE-89",
        evidence_reference="time_based_sleep_payload_5000ms",
        remediation_recommendation="Use parameterized prepared statements immediately.",
    )
    t = list(skill._tasks.values())[0]
    t.findings.append(crit_finding)

    alerts = operator.run_cycle()
    assert any(a["severity"] == "CRITICAL" and "SQL injection" in a["voice_message"] for a in alerts)

    # 2. Inject new HIGH finding
    high_finding = SecurityFinding(
        finding_id="f-high-02",
        title="Broken Object Level Authorization on user profile",
        severity="HIGH",
        target_asset="https://mywebsite.com/api/users/profile",
        description="Insecure direct object reference exposes profile data.",
        cve_or_cwe="CWE-639",
        evidence_reference="idor_token_swap_test",
        remediation_recommendation="Enforce user session tenancy checks on record lookup.",
    )
    t.findings.append(high_finding)
    alerts2 = operator.run_cycle()
    assert any(a["severity"] == "HIGH" and "high-severity finding" in a["voice_message"] for a in alerts2)

    # 3. Test pending approval reminder (>30 min)
    act = SentinelPendingAction(
        action_id="act-stale",
        task_id="sec-task-101",
        action_name="Active Webhook Bypass Check",
        target="https://mywebsite.com/webhook",
        impact_level="HIGH_IMPACT",
        evidence="Webhook signature verification missing.",
        rationale="Verify signature enforcement.",
        status="PENDING",
    )
    skill._pending_actions[act.action_id] = act
    operator.vigilance_state.pending_approvals_since = datetime.now(timezone.utc) - timedelta(minutes=35)
    alerts3 = operator.run_cycle()
    assert any(a["severity"] == "WARNING" and "pending approval for over 30 minutes" in a["voice_message"] for a in alerts3)

    # 4. Test Sentinel Unreachable (>2 min)
    skill.get_sentinel_health = lambda: {"status": "DOWN"}
    operator.vigilance_state.unreachable_since = datetime.now(timezone.utc) - timedelta(minutes=3)
    alerts4 = operator.run_cycle()
    assert any(a["severity"] == "CRITICAL" and "unreachable for more than 2 minutes" in a["voice_message"] for a in alerts4)
