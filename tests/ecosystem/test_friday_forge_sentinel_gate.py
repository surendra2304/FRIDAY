# -*- coding: utf-8 -*-
"""End-to-End Test: Forge - Sentinel Deployment Security Gate.

Validates:
1. Forge completes service build output.
2. FRIDAY submits Sentinel API security scan before deployment.
3. Critical findings strictly block deployment (BLOCKED).
4. High findings issue warnings requiring review (WARNED).
5. Clean deliverables pass gate (PASSED).
"""

from friday.ecosystem.asset_registry import AssetRegistry
from friday.skills.sentinel_manager import SentinelManagerSkill, SecurityFinding
from friday.workflows.security_coordination import SecurityCoordinationWorkflow


def test_forge_deployment_security_gating_levels():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    # 1. Clean build -> PASSED
    gate_clean = workflow.evaluate_deployment_security_gate(
        build_task_id="forge-build-101",
        service_target="http://localhost:8000/clean_api",
    )
    assert gate_clean["decision"] == "PASSED"
    assert "PASSED" in gate_clean["reason"]

    # 2. High vulnerability -> WARNED
    high_finding = SecurityFinding(
        finding_id="f-high-cors",
        title="Overly Permissive CORS Policy",
        severity="HIGH",
        target_asset="http://localhost:8000/warn_api",
        description="Access-Control-Allow-Origin: * on authenticated routes.",
        cve_or_cwe="CWE-346",
        evidence_reference="cors_header_reflection",
        remediation_recommendation="Restrict allowed origins to trusted domains.",
    )
    sentinel._tasks["sec-task-101"].findings.append(high_finding)
    gate_warn = workflow.evaluate_deployment_security_gate(
        build_task_id="forge-build-102",
        service_target="http://localhost:8000/warn_api",
    )
    assert gate_warn["decision"] == "WARNED"
    assert gate_warn["high_count"] >= 1

    # 3. Critical vulnerability -> BLOCKED
    crit_finding = SecurityFinding(
        finding_id="f-crit-sqli",
        title="Blind SQL Injection in User Search",
        severity="CRITICAL",
        target_asset="http://localhost:8000/blocked_api",
        description="Unparameterized search query allows data extraction.",
        cve_or_cwe="CWE-89",
        evidence_reference="sleep_probe_5000ms",
        remediation_recommendation="Use parameterized ORM queries.",
    )
    sentinel._tasks["sec-task-101"].findings.append(crit_finding)
    gate_blocked = workflow.evaluate_deployment_security_gate(
        build_task_id="forge-build-103",
        service_target="http://localhost:8000/blocked_api",
    )
    assert gate_blocked["decision"] == "BLOCKED"
    assert gate_blocked["critical_count"] >= 1
