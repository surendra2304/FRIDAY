"""End-to-End Test: Sentinel HIGH_IMPACT Action Approval Workflow.

Validates:
1. Sentinel registers high-impact dynamic verification action.
2. Action enters FRIDAY pending approval queue (SENSITIVE clearance).
3. Spoken voice command "Approve that security action" reviews evidence and approves.
4. Verified that Sentinel action status transitions to APPROVED.
"""

from friday.skills.sentinel_manager import SentinelManagerSkill, SentinelPendingAction


def test_sentinel_high_impact_approval_lifecycle():
    skill = SentinelManagerSkill()

    # 1. Register high impact action
    action = SentinelPendingAction(
        action_id="act-sqli-verify",
        task_id="sec-task-101",
        action_name="Blind SQL Injection Dynamic Payload Verification",
        target="https://example.com/api/checkout",
        impact_level="HIGH_IMPACT",
        evidence="Time-delay sleep payload response measured 5.2s.",
        rationale="Confirm vulnerability without performing destructive write queries.",
        status="PENDING",
    )
    skill._pending_actions[action.action_id] = action

    # Verify pending
    health = skill.get_sentinel_health()
    assert health["pending_approvals_count"] >= 1

    # 2. Voice command: "Approve that security action"
    res = skill.execute("Approve that security action")
    assert res.success is True
    assert "Security Action Approved" in res.output
    assert "[SENSITIVE CLEARANCE GRANTED]" in res.output
    assert "Blind SQL Injection Dynamic Payload Verification" in res.output

    # 3. Verify action state updated
    assert skill._pending_actions["act-sqli-verify"].status == "APPROVED"
