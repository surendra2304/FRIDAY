# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for Nexus-Sentinel Security Coordination & Asset Registry.

Validates:
1. AssetRegistry inventory tracking, posture scoring, risk classification, and highest-risk asset detection.
2. SecurityCoordinationWorkflow:
   - NEW_ASSET_DETECTED: automated passive_recon scan on new assets and critical incident creation.
   - INCIDENT_RESPONSE: correlating Nexus anomalies with targeted Sentinel scans.
   - DEPLOYMENT_SECURITY_GATE: gating Forge builds (blocking critical, warning high).
   - VULNERABILITY_MONITORING: exposure audits on newly discovered CVEs.
3. SecurityPostureDashboard: panel data assembly and Markdown dashboard rendering.
4. Voice command execution:
   - "What's my security posture?"
   - "Which asset is most at risk?"
   - "When was my website last scanned?"
"""

import pytest

from friday.core.types import TrustLevel
from friday.ecosystem.asset_registry import AssetRegistry, SecurableAsset, AssetType
from friday.skills.sentinel_manager import SentinelManagerSkill, SecurityFinding
from friday.workflows.security_coordination import SecurityCoordinationWorkflow
from friday.ui.security_panel import SecurityPostureDashboard


def test_asset_registry_and_posture_score():
    registry = AssetRegistry()
    assets = registry.get_all_assets()
    assert len(assets) >= 4

    # Posture score calculation
    posture = registry.calculate_security_posture_score()
    assert 0 <= posture["score"] <= 100
    assert posture["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value
    assert "rating" in posture

    # Highest risk asset detection
    highest = registry.get_highest_risk_asset()
    assert highest is not None
    assert highest.asset_id == "asset-nexus-web"
    assert highest.risk_level == "MEDIUM"

    # Dynamic update of scan result
    registry.update_scan_result(
        "asset-forge-api",
        findings=[{"severity": "CRITICAL", "title": "SQLi"}],
        mode="api_security",
    )
    forge_asset = registry.get_asset("asset-forge-api")
    assert forge_asset.risk_level == "CRITICAL"
    assert forge_asset.critical_findings_count == 1

    updated_posture = registry.calculate_security_posture_score()
    assert updated_posture["critical"] >= 1
    assert updated_posture["score"] < posture["score"]


def test_new_asset_detected_workflow():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    # Trigger new asset detection
    res = workflow.handle_new_asset_detected(
        asset_name="Nexus Blog Subdomain",
        target="blog.example.com",
        subsystem="nexus",
        asset_type=AssetType.DOMAIN,
    )
    assert res["success"] is True
    assert res["workflow"] == "NEW_ASSET_DETECTED"
    assert res["target"] == "blog.example.com"
    assert res["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # Verify registered in AssetRegistry
    created = registry.get_asset(res["asset_id"])
    assert created is not None
    assert created.target == "blog.example.com"


def test_incident_response_correlation_workflow():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    incident_report = workflow.handle_incident_response(
        incident_id="inc-traffic-502",
        target="https://example.com/api/checkout",
        anomaly_type="502_error_spike_after_high_traffic",
    )
    assert incident_report["incident_id"] == "inc-traffic-502"
    assert "correlation_summary" in incident_report
    assert incident_report["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value


def test_deployment_security_gating_workflow():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    # 1. Clean build output -> PASSED
    gate1 = workflow.evaluate_deployment_security_gate(
        build_task_id="forge-task-1",
        service_target="http://localhost:8000/clean_service",
    )
    assert gate1["success"] is True
    assert gate1["decision"] in ("PASSED", "WARNED")

    # 2. Inject Critical finding to Sentinel -> BLOCKED
    crit_finding = SecurityFinding(
        finding_id="f-gate-crit",
        title="Unauthenticated Remote Code Execution",
        severity="CRITICAL",
        target_asset="http://localhost:8000/vulnerable_service",
        description="Arbitrary command execution via deserialization.",
        cve_or_cwe="CWE-502",
        evidence_reference="deserialization_poc",
        remediation_recommendation="Disable unsafe deserialization.",
    )
    sentinel._tasks["sec-task-101"].findings.append(crit_finding)

    gate2 = workflow.evaluate_deployment_security_gate(
        build_task_id="forge-task-2",
        service_target="http://localhost:8000/vulnerable_service",
    )
    assert gate2["decision"] == "BLOCKED"
    assert "BLOCKED" in gate2["reason"]
    assert gate2["critical_count"] >= 1


def test_vulnerability_monitoring_workflow():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    cve_report = workflow.handle_vulnerability_monitoring(
        cve_id="CVE-2026-38291",
        affected_package="fastapi",
        severity="HIGH",
    )
    assert cve_report["cve_id"] == "CVE-2026-38291"
    assert cve_report["is_exposed"] is True
    assert "Nexus Primary Website" in cve_report["exposed_assets"]
    assert "voice_alert" in cve_report


def test_security_posture_dashboard_rendering():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    dashboard = SecurityPostureDashboard(registry=registry, sentinel_skill=sentinel)

    panel_data = dashboard.render_panel_data()
    assert panel_data["title"] == "FRIDAY Unified Security Posture Dashboard"
    assert len(panel_data["assets"]) >= 4
    assert len(panel_data["trend"]) == 7

    md_output = dashboard.render_markdown_dashboard()
    assert "FRIDAY Security Posture Dashboard" in md_output
    assert "Asset Inventory & Risk Posture" in md_output
    assert "Discovered Attack Surface" in md_output


def test_voice_security_queries():
    skill = SentinelManagerSkill()

    # 1. "What's my security posture?"
    res1 = skill.execute("What's my security posture?")
    assert res1.success is True
    assert "Ecosystem Security Posture" in res1.output
    assert "/100" in res1.output

    # 2. "Which asset is most at risk?"
    res2 = skill.execute("Which asset is most at risk?")
    assert res2.success is True
    assert "Highest Risk Asset" in res2.output

    # 3. "When was my website last scanned?"
    res3 = skill.execute("When was my website last scanned?")
    assert res3.success is True
    assert "Website Security Scan Status" in res3.output
    assert "Last Scanned" in res3.output
