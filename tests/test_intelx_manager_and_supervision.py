"""Comprehensive Test Suite for IntelX Deep Research Integration.

Validates:
1. IntelXManagerSkill API operations:
   - submit_research with domain hints (security, market, technical, competitive, general) and depth (quick_scan, standard, deep_dive)
   - get_research_status, get_research_findings, get_research_report, get_contradictions, cancel_research, get_intelx_health
2. Natural language voice commands:
   - "Research [topic]" (auto domain detection)
   - "Deep dive into [topic]"
   - "Quick scan on [topic]"
   - "What did the research find?"
   - "Show me the research report"
   - "Any contradictions in the research?"
   - "Cancel the research"
   - "Research status"
3. ResearchSupervisorOperator 60s cycle:
   - Alert on research completion with findings and contradiction breakdown
   - Mid-run contradiction detection alert
   - Research failure alert
   - IntelX unreachable > 2 minutes critical alert
4. Security & Trust Invariant:
   - All research artifacts carry TrustLevel.UNTRUSTED_EXTERNAL
"""

from datetime import datetime, timedelta, timezone

from friday.core.types import TrustLevel
from friday.operators.research_supervisor_operator import ResearchSupervisorOperator
from friday.skills.intelx_manager import (
    IntelXManagerSkill,
    ResearchContradiction,
    ResearchFinding,
    ResearchRun,
)


def test_intelx_manager_api_operations():
    skill = IntelXManagerSkill()

    # 1. Health check
    health = skill.get_intelx_health()
    assert health["status"] == "HEALTHY"
    assert health["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Domain Auto-Detection
    assert skill.auto_detect_domain("Post-quantum lattice cryptographic standards") == "security"
    assert skill.auto_detect_domain("Bitcoin ETF liquidity inflows and macro yield curves") == "market"
    assert skill.auto_detect_domain("Rust asynchronous runtime memory models") == "technical"
    assert skill.auto_detect_domain("SaaS pricing models and market share competitors") == "competitive"

    # 3. Submit research across depths
    res_quick = skill.submit_research("Solana throughput benchmark", depth="quick_scan")
    assert res_quick["success"] is True
    assert res_quick["depth"] == "quick_scan"
    assert res_quick["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    res_deep = skill.submit_research("Zero-knowledge rollup validation costs", depth="deep_dive")
    assert res_deep["success"] is True
    assert res_deep["depth"] == "deep_dive"

    # 4. Query status
    status = skill.get_research_status(res_quick["run_id"])
    assert status["success"] is True
    assert status["phase"] == "SEARCHING"

    # 5. Query findings with confidence ranking
    findings = skill.get_research_findings()
    assert len(findings) >= 2
    assert findings[0]["confidence"] >= findings[1]["confidence"]
    assert findings[0]["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 6. Query contradictions
    contras = skill.get_contradictions()
    assert len(contras) >= 1
    assert contras[0]["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 7. Query reports (markdown and JSON)
    rep_md = skill.get_research_report(report_format="markdown")
    assert rep_md["success"] is True
    assert "Verified Findings" in rep_md["markdown_report"]

    rep_json = skill.get_research_report(report_format="json")
    assert rep_json["success"] is True
    assert isinstance(rep_json["findings"], list)

    # 8. Cancel research
    cancel_res = skill.cancel_research(res_quick["run_id"])
    assert cancel_res["success"] is True
    assert cancel_res["status"] == "CANCELLED"


def test_intelx_manager_voice_commands():
    skill = IntelXManagerSkill()

    # 1. "Research [topic]"
    res1 = skill.execute("Research Ethereum L2 compression algorithms")
    assert res1.success is True
    assert "IntelX Research Task Submitted" in res1.output

    # 2. "Deep dive into [topic]"
    res2 = skill.execute("Deep dive into Homomorphic Encryption benchmarks")
    assert res2.success is True
    assert "IntelX Deep Dive Initiated" in res2.output

    # 3. "Quick scan on [topic]"
    res3 = skill.execute("Quick scan on SQLite WAL performance")
    assert res3.success is True
    assert "IntelX Quick Scan Initiated" in res3.output

    # 4. "What did the research find?"
    res4 = skill.execute("What did the research find?")
    assert res4.success is True
    assert "IntelX Research Findings" in res4.output

    # 5. "Show me the research report"
    res5 = skill.execute("Show me the research report")
    assert res5.success is True
    assert "IntelX Research Report Highlights" in res5.output

    # 6. "Any contradictions in the research?"
    res6 = skill.execute("Any contradictions in the research?")
    assert res6.success is True
    assert "Disputed Claims & Contradictions" in res6.output

    # 7. "Cancel the research"
    skill.submit_research("Active research on decentralized compute", depth="standard")
    res7 = skill.execute("Cancel the research")
    assert res7.success is True
    assert "Research Cancelled" in res7.output

    # 8. "Research status"
    res8 = skill.execute("Research status")
    assert res8.success is True
    assert "IntelX Research Status" in res8.output


def test_research_supervisor_operator_alerts():
    skill = IntelXManagerSkill()
    operator = ResearchSupervisorOperator(skill=skill, poll_interval_sec=60.0)

    # Initial cycle
    operator.run_cycle()

    # 1. Research Completion Alert
    new_run = ResearchRun(
        run_id="intelx-run-complete-test",
        question="Quantum Key Distribution network topology",
        domain_hint="security",
        depth="standard",
        phase="COMPLETED",
        progress_pct=100.0,
        findings=[
            ResearchFinding(
                finding_id="f-qkd-1",
                run_id="intelx-run-complete-test",
                claim="Trusted node networks currently bridge continental distances.",
                confidence=0.95,
            )
        ],
        contradictions=[
            ResearchContradiction(
                contradiction_id="contra-qkd-1",
                run_id="intelx-run-complete-test",
                topic="Repeater Feasibility",
                claim_a="Feasible by 2028",
                source_a="Lab A",
                evidence_a="Tested memory",
                claim_b="Decade away",
                source_b="Lab B",
                evidence_b="Coherence drops",
            )
        ],
    )
    skill._runs[new_run.run_id] = new_run

    alerts = operator.run_cycle()
    assert any(a["severity"] == "INFO" and "Quantum Key Distribution" in a["voice_message"] for a in alerts)
    assert any("1 verified findings, 1 disputed" in a["voice_message"] for a in alerts)

    # 2. Mid-Run Contradiction Alert
    new_contra = ResearchContradiction(
        contradiction_id="contra-mid-run-102",
        run_id="intelx-run-complete-test",
        topic="Satellite Downlink Bitrates",
        claim_a="10 Mbps demonstrated",
        source_a="Micius Team",
        evidence_a="Optical downlink log",
        claim_b="Maximum 1 Mbps in daylight",
        source_b="Atmospheric Optical Review",
        evidence_b="Solar background noise limit",
    )
    new_run.contradictions.append(new_contra)
    alerts2 = operator.run_cycle()
    assert any(a["severity"] == "INFO" and "Satellite Downlink Bitrates" in a["title"] for a in alerts2)

    # 3. Research Failure Alert
    fail_run = ResearchRun(
        run_id="intelx-run-fail",
        question="Obscure proprietary system internals",
        domain_hint="technical",
        depth="standard",
        phase="FAILED",
        progress_pct=40.0,
        failure_reason="Source paywall and strict rate limits encountered",
    )
    skill._runs[fail_run.run_id] = fail_run
    alerts3 = operator.run_cycle()
    assert any(a["severity"] == "WARNING" and "failed" in a["voice_message"] for a in alerts3)

    # 4. IntelX Unreachable Alert (> 2 minutes)
    skill.get_intelx_health = lambda: {"status": "DOWN"}
    operator.supervisor_state.unreachable_since = datetime.now(timezone.utc) - timedelta(minutes=3)
    alerts4 = operator.run_cycle()
    assert any(a["severity"] == "CRITICAL" and "unreachable for more than 2 minutes" in a["voice_message"] for a in alerts4)
