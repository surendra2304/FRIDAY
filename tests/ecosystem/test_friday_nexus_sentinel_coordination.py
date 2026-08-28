# -*- coding: utf-8 -*-
"""End-to-End Test: Nexus - Sentinel Security Coordination.

Validates:
1. Nexus reports new subdomain / deployment asset.
2. FRIDAY auto-submits Sentinel passive_recon scan on discovered asset.
3. Critical finding automatically creates Nexus incident and alerts operator.
"""

from friday.ecosystem.asset_registry import AssetRegistry, AssetType
from friday.skills.sentinel_manager import SentinelManagerSkill, SecurityFinding
from friday.workflows.security_coordination import SecurityCoordinationWorkflow
from friday.core.types import TrustLevel


def test_nexus_new_asset_detection_and_incident_creation():
    sentinel = SentinelManagerSkill()
    registry = AssetRegistry()
    workflow = SecurityCoordinationWorkflow(sentinel_skill=sentinel, registry=registry)

    # 1. Nexus discovers new marketing landing page
    target_domain = "promo.example.com"
    event = workflow.handle_new_asset_detected(
        asset_name="Nexus Promo Campaign Site",
        target=target_domain,
        subsystem="nexus",
        asset_type=AssetType.DOMAIN,
    )

    assert event["success"] is True
    assert event["target"] == target_domain
    assert event["workflow"] == "NEW_ASSET_DETECTED"
    assert event["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # Verify asset is stored in AssetRegistry
    asset = registry.get_asset(event["asset_id"])
    assert asset is not None
    assert asset.target == target_domain

    # 2. Inject Critical finding into Sentinel task to simulate incident creation
    crit = SecurityFinding(
        finding_id="f-crit-subdomain-takeover",
        title="Dangling CNAME DNS Subdomain Takeover",
        severity="CRITICAL",
        target_asset=target_domain,
        description="CNAME points to unclaimed S3 bucket.",
        cve_or_cwe="CWE-284",
        evidence_reference="dns_cname_lookup_nxdomain",
        remediation_recommendation="Remove dangling DNS record or claim cloud storage bucket.",
    )
    sentinel._tasks[event["task_id"]].findings.append(crit)

    # Re-evaluate asset scan result
    event_crit = workflow.handle_new_asset_detected(
        asset_name="Nexus Promo Campaign Site",
        target=target_domain,
        subsystem="nexus",
        asset_type=AssetType.DOMAIN,
    )
    assert event_crit["critical_findings"] >= 1
    assert event_crit["incident_created"] is True
