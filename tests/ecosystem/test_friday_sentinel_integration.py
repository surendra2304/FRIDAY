"""End-to-End Test: FRIDAY - Sentinel Integration.

Validates:
1. Voice command "Run security scan" -> SentinelManagerSkill delegates to Sentinel API.
2. Mocked response with findings parsed and formatted for voice readout.
3. Verification that critical finding triggers immediate voice alert via SentinelVigilanceOperator.
"""

from friday.core.types import TrustLevel
from friday.operators.sentinel_vigilance_operator import SentinelVigilanceOperator
from friday.skills.sentinel_manager import SecurityFinding, SentinelManagerSkill


def test_voice_command_run_security_scan_and_alert_on_critical():
    # 1. Initialize skill with mock API delegation client
    calls = []

    def mock_api_client(method: str, url: str, payload: dict):
        calls.append({"method": method, "url": url, "payload": payload})
        return {
            "success": True,
            "task_id": "sec-task-909",
            "target": payload.get("target"),
            "mode": payload.get("mode"),
            "phase": "RECON",
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }

    skill = SentinelManagerSkill(
        default_target_domain="myproductionapp.com",
        api_client=mock_api_client,
    )

    # 2. Voice command: "Run a security scan on my website"
    result = skill.execute("Run a security scan on my website")
    assert result.success is True
    assert "Security scan initiated for **myproductionapp.com**" in result.output
    assert "Passive Recon Task" in result.output
    assert len(calls) == 2  # passive_recon + full_web

    # 3. Sentinel findings formatted for voice & text
    findings = skill.get_findings()
    assert len(findings) >= 2
    assert findings[0]["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 4. Critical finding triggers immediate voice alert in Vigilance Operator
    operator = SentinelVigilanceOperator(skill=skill, poll_interval_sec=60.0)
    operator.run_cycle()  # Baseline run

    crit_finding = SecurityFinding(
        finding_id="f-crit-auth-bypass",
        title="Authentication Bypass via JWT Signature Confusion",
        severity="CRITICAL",
        target_asset="https://myproductionapp.com/api/v1/auth",
        description="Public key used as HMAC secret enables token forgery.",
        cve_or_cwe="CWE-347",
        evidence_reference="jwt_none_algorithm_probe",
        remediation_recommendation="Strictly enforce asymmetric signature algorithms (RS256/ES256).",
    )
    t = list(skill._tasks.values())[0]
    t.findings.append(crit_finding)

    alerts = operator.run_cycle()
    assert any(
        a["severity"] == "CRITICAL"
        and "Authentication Bypass" in a["title"]
        and "Critical security finding on your website" in a["voice_message"]
        for a in alerts
    )
