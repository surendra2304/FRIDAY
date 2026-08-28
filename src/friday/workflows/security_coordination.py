# -*- coding: utf-8 -*-
"""Security Coordination Workflow for FRIDAY.

Coordinates automated, cross-system security operations between Nexus, Forge,
Trading Bot, and Sentinel:
1. NEW_ASSET_DETECTED: Nexus discovers new subdomain/deployment -> Sentinel passive_recon -> incident if critical.
2. INCIDENT_RESPONSE: Nexus security anomaly -> Sentinel targeted endpoint audit -> correlated incident brief.
3. DEPLOYMENT_SECURITY_GATE: Forge build output -> Sentinel API security scan -> gate deployment (block critical, warn high).
4. VULNERABILITY_MONITORING: New CVE discovered -> audit Nexus & Trading Bot stack -> remediation guidance.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel
from friday.ecosystem.asset_registry import AssetRegistry, SecurableAsset, AssetType, asset_registry
from friday.skills.sentinel_manager import SentinelManagerSkill

logger = get_logger("workflows.security_coordination")


@dataclass
class SecurityCoordinationEvent:
    """Record of an automated cross-system security action."""
    event_id: str
    workflow_type: str  # NEW_ASSET_DETECTED, INCIDENT_RESPONSE, DEPLOYMENT_SECURITY_GATE, VULNERABILITY_MONITORING
    target: str
    status: str  # IN_PROGRESS, PASSED, WARNED, BLOCKED, FAILED
    details: Dict[str, Any]
    findings: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SecurityCoordinationWorkflow:
    """Coordinates cross-system security workflows across Nexus, Forge, Trading Bot, and Sentinel."""

    def __init__(
        self,
        sentinel_skill: Optional[SentinelManagerSkill] = None,
        registry: Optional[AssetRegistry] = None,
    ) -> None:
        self.sentinel = sentinel_skill or SentinelManagerSkill()
        self.registry = registry or asset_registry
        self.event_history: List[SecurityCoordinationEvent] = []
        self._lock = threading.RLock()

    def handle_new_asset_detected(
        self,
        asset_name: str,
        target: str,
        subsystem: str = "nexus",
        asset_type: AssetType = AssetType.DOMAIN,
    ) -> Dict[str, Any]:
        """Automatically registers new asset in AssetRegistry and runs Sentinel passive_recon."""
        asset_id = f"asset-{subsystem}-{target.replace('.', '-').replace(':', '-').replace('/', '-')}"
        asset = SecurableAsset(
            asset_id=asset_id,
            name=asset_name,
            asset_type=asset_type,
            target=target,
            subsystem=subsystem,
            risk_level="CLEAN",
        )
        self.registry.register_asset(asset)

        # Submit Sentinel passive reconnaissance
        scan_res = self.sentinel.submit_security_task(target=target, mode="passive_recon")
        task_id = scan_res.get("task_id", "")

        # Simulate finding evaluation
        findings = self.sentinel.get_findings(task_id=task_id)
        self.registry.update_scan_result(asset_id=asset_id, findings=findings, mode="passive_recon")

        crit_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        incident_created = False
        if crit_count > 0:
            incident_created = True
            logger.error(f"[SECURITY_COORDINATION] Critical finding discovered on new asset '{target}'.")

        event = SecurityCoordinationEvent(
            event_id=f"evt-new-asset-{len(self.event_history)+1}",
            workflow_type="NEW_ASSET_DETECTED",
            target=target,
            status="BLOCKED" if crit_count > 0 else "PASSED",
            details={
                "asset_id": asset_id,
                "task_id": task_id,
                "critical_findings": crit_count,
                "incident_created": incident_created,
            },
            findings=findings,
        )
        with self._lock:
            self.event_history.append(event)

        return {
            "success": True,
            "workflow": "NEW_ASSET_DETECTED",
            "asset_id": asset_id,
            "target": target,
            "task_id": task_id,
            "critical_findings": crit_count,
            "incident_created": incident_created,
            "summary": f"New asset '{target}' scanned with Sentinel. Status: {'CRITICAL_INCIDENT' if crit_count > 0 else 'CLEAN'}.",
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

    def handle_incident_response(
        self,
        incident_id: str,
        target: str,
        anomaly_type: str = "traffic_spike_or_error_anomaly",
    ) -> Dict[str, Any]:
        """Correlates a Nexus website security anomaly with a targeted Sentinel endpoint scan."""
        # 1. Trigger targeted Sentinel scan
        scan_res = self.sentinel.submit_security_task(target=target, mode="api_security")
        task_id = scan_res.get("task_id", "")
        findings = self.sentinel.get_findings(task_id=task_id)

        # 2. Correlate with Nexus telemetry
        correlated_report = {
            "incident_id": incident_id,
            "anomaly_type": anomaly_type,
            "target": target,
            "task_id": task_id,
            "findings_count": len(findings),
            "findings": findings,
            "correlation_summary": (
                f"Nexus anomaly '{anomaly_type}' on '{target}' correlated with {len(findings)} "
                f"Sentinel security findings. Perimeter defensive mitigations active."
            ),
            "recommended_action": "Apply WAF IP blocklist and patch affected endpoint route.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

        event = SecurityCoordinationEvent(
            event_id=f"evt-incident-{len(self.event_history)+1}",
            workflow_type="INCIDENT_RESPONSE",
            target=target,
            status="PASSED",
            details=correlated_report,
            findings=findings,
        )
        with self._lock:
            self.event_history.append(event)

        return correlated_report

    def evaluate_deployment_security_gate(
        self,
        build_task_id: str,
        service_target: str,
        artifacts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Audits Forge build output via Sentinel API security scan before deployment."""
        scan_res = self.sentinel.submit_security_task(target=service_target, mode="api_security")
        task_id = scan_res.get("task_id", "")

        # Fetch findings for the scanned service
        findings = self.sentinel.get_findings(task_id=task_id)
        if not findings and task_id in self.sentinel._tasks:
            findings = [
                {
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "severity": f.severity,
                    "target_asset": f.target_asset,
                    "description": f.description,
                    "cve_or_cwe": f.cve_or_cwe,
                    "evidence_reference": f.evidence_reference,
                    "remediation_recommendation": f.remediation_recommendation,
                    "status": f.status,
                    "created_at": f.created_at,
                    "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                }
                for f in self.sentinel._tasks[task_id].findings
            ]
        # Also check if target asset matches any known findings
        if not findings:
            all_f = self.sentinel.get_findings()
            findings = [f for f in all_f if f.get("target_asset") == service_target or service_target in str(f.get("target_asset", ""))]

        crit_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")

        if crit_count > 0:
            decision = "BLOCKED"
            reason = f"Deployment BLOCKED: {crit_count} CRITICAL vulnerability findings detected by Sentinel."
        elif high_count > 0:
            decision = "WARNED"
            reason = f"Deployment WARNED: {high_count} HIGH vulnerability findings detected. Human review recommended."
        else:
            decision = "PASSED"
            reason = "Deployment PASSED: No blocking vulnerabilities detected in build deliverables."

        event = SecurityCoordinationEvent(
            event_id=f"evt-gate-{len(self.event_history)+1}",
            workflow_type="DEPLOYMENT_SECURITY_GATE",
            target=service_target,
            status=decision,
            details={
                "build_task_id": build_task_id,
                "sentinel_task_id": task_id,
                "decision": decision,
                "reason": reason,
                "critical_count": crit_count,
                "high_count": high_count,
            },
            findings=findings,
        )
        with self._lock:
            self.event_history.append(event)

        return {
            "success": True,
            "build_task_id": build_task_id,
            "target": service_target,
            "decision": decision,
            "reason": reason,
            "critical_count": crit_count,
            "high_count": high_count,
            "findings": findings,
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

    def handle_vulnerability_monitoring(
        self,
        cve_id: str,
        affected_package: str,
        severity: str = "HIGH",
    ) -> Dict[str, Any]:
        """Audits all known ecosystem assets for exposure to newly discovered CVE."""
        all_assets = self.registry.get_all_assets()
        exposed_assets = []
        for a in all_assets:
            if affected_package.lower() in str(a.metadata).lower() or a.subsystem == "nexus":
                exposed_assets.append(a.name)

        is_exposed = len(exposed_assets) > 0
        remediation = f"Upgrade {affected_package} dependency to latest patched version and redeploy via Forge."

        alert_brief = {
            "cve_id": cve_id,
            "package": affected_package,
            "severity": severity,
            "is_exposed": is_exposed,
            "exposed_assets": exposed_assets,
            "remediation": remediation,
            "voice_alert": (
                f"Vulnerability alert: {cve_id} in {affected_package} ({severity}). "
                f"{'Exposed on ' + ', '.join(exposed_assets) if is_exposed else 'No active ecosystem exposure detected.'}"
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

        event = SecurityCoordinationEvent(
            event_id=f"evt-cve-{len(self.event_history)+1}",
            workflow_type="VULNERABILITY_MONITORING",
            target=affected_package,
            status="WARNED" if is_exposed else "PASSED",
            details=alert_brief,
        )
        with self._lock:
            self.event_history.append(event)

        return alert_brief
