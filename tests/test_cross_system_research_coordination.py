"""Comprehensive Test Suite for Cross-System Research Coordination.

Validates:
1. ResearchLibrary persistence, search, cross-reference detection, and 90-day confidence-weighted decay.
2. ResearchContextInjector injection across Trading, Security, Forge, and Nexus execution contexts.
3. ResearchCoordinationWorkflow cross-system triggers:
   - SECURITY_RESEARCH_TRIGGER (Sentinel critical CVE discovery)
   - MARKET_RESEARCH_TRIGGER (Trading Bot volatility anomaly - advisory only)
   - COMPETITIVE_RESEARCH_TRIGGER (Nexus competitor mention)
   - TECHNICAL_RESEARCH_TRIGGER (Forge unfamiliar architecture specification)
4. Trust & Security Invariants:
   - All research context strictly carries TrustLevel.UNTRUSTED_EXTERNAL
"""

from datetime import datetime, timedelta, timezone

from friday.core.types import TrustLevel
from friday.memory.research_library import ResearchArchiveEntry, ResearchLibrary
from friday.skills.intelx_manager import IntelXManagerSkill
from friday.skills.research_context import ResearchContextInjector
from friday.workflows.research_coordination import ResearchCoordinationWorkflow


def test_research_library_storage_search_and_cross_referencing():
    library = ResearchLibrary()

    # 1. Save Research Entry
    entry = library.save_research_entry(
        run_id="run-zk-101",
        topic="Zero-knowledge rollup transaction verification overhead on Ethereum L1",
        domain="technical",
        depth="deep_dive",
        findings=[
            {
                "finding_id": "f-zk-01",
                "claim": "STARK proofs incur higher calldata costs than SNARKs but avoid trusted setups.",
                "confidence": 0.94,
                "citations": ["StarkWare Whitepaper", "Ethereum Foundation L2 Research"],
            }
        ],
        contradictions_count=0,
    )
    assert entry.entry_id is not None
    assert entry.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Search library
    results = library.search(query="Zero-knowledge STARK calldata", domain="technical")
    assert len(results) >= 1
    assert "Zero-knowledge" in results[0]["topic"]

    # 3. Cross-reference detection
    cross_refs = library.find_cross_references(topic="Quantum computing cryptography")
    assert len(cross_refs) >= 1
    assert "Quantum" in cross_refs[0]["related_topic"]


def test_research_library_confidence_weighted_retention_decay():
    library = ResearchLibrary()

    # Add expired low confidence entry (age = 40 days, allowed = 30 days)
    old_low = ResearchArchiveEntry(
        entry_id="arch-old-low",
        run_id="run-old-01",
        topic="Unverified rumor on asset listing",
        domain="market",
        depth="quick_scan",
        findings=[],
        contradictions_count=0,
        created_at=(datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
    )
    library._entries[old_low.entry_id] = old_low

    decay_res = library.apply_retention_decay(base_retention_days=90)
    assert decay_res["purged_count"] >= 1
    assert "arch-old-low" in decay_res["purged_entries"]


def test_research_context_injector_all_subsystems():
    library = ResearchLibrary()
    injector = ResearchContextInjector(library=library)

    # 1. Trading Context (Advisory Only)
    base_trade = {"status": "ACTIVE", "portfolio_value": 250000.0}
    enriched_trade = injector.inject_trading_market_context(base_trade, asset="BTC")
    assert "market_research_context" in enriched_trade
    assert "prohibited" in enriched_trade["market_research_context"]["advisory_disclaimer"]
    assert enriched_trade["market_research_context"]["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Security Threat Context
    base_sec = {"posture_score": 92.0, "status": "SECURE"}
    enriched_sec = injector.inject_security_threat_context(base_sec, cve_or_vulnerability="CVE-2026-4401 Critical RCE")
    assert "threat_research_context" in enriched_sec
    assert enriched_sec["threat_research_context"]["remediation_priority"] == "CRITICAL_ELEVATED"

    # 3. Forge Technical Context
    base_forge = {"task_id": "task-dash-01", "goal": "Build real-time dashboard"}
    enriched_forge = injector.inject_forge_technical_context(base_forge, architecture_topic="WebSocket vs SSE")
    assert "technical_research_context" in enriched_forge

    # 4. Nexus Competitive Context
    base_nexus = {"visitors_today": 1200, "leads": 4}
    enriched_nexus = injector.inject_nexus_competitive_context(base_nexus, competitor_name="AcmeAnalytics")
    assert "competitive_research_context" in enriched_nexus


def test_cross_system_research_coordination_triggers():
    intelx = IntelXManagerSkill()
    library = ResearchLibrary()
    workflow = ResearchCoordinationWorkflow(intelx_skill=intelx, library=library)

    # 1. Security Trigger (Critical CVE discovery)
    sec_res = workflow.handle_security_vulnerability_trigger(
        cve_id="CVE-2026-9901",
        vulnerability_title="Remote Code Execution via Header Deserialization",
        severity="CRITICAL",
    )
    assert sec_res["success"] is True
    assert sec_res["trigger"] == "SECURITY_RESEARCH_TRIGGER"
    assert sec_res["findings_count"] >= 1
    assert sec_res["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Market Trigger (Trading Volatility)
    mkt_res = workflow.handle_market_volatility_trigger(
        asset="ETH",
        price_change_pct=+8.4,
        condition_note="Sudden liquidity cascade",
    )
    assert mkt_res["success"] is True
    assert mkt_res["trigger"] == "MARKET_RESEARCH_TRIGGER"
    assert "institutional" in mkt_res["advisory_context"]

    # 3. Competitive Trigger (Nexus Competitor Detection)
    comp_res = workflow.handle_competitive_intelligence_trigger(
        competitor_name="CompetitorX",
        source_context="Enterprise visitor comparison query",
    )
    assert comp_res["success"] is True
    assert comp_res["trigger"] == "COMPETITIVE_RESEARCH_TRIGGER"

    # 4. Technical Trigger (Forge Unfamiliar Stack)
    tech_res = workflow.handle_technical_architecture_trigger(
        architecture_question="WebSocket vs SSE for live stock orderbooks",
        forge_task_id="forge-build-404",
    )
    assert tech_res["success"] is True
    assert tech_res["trigger"] == "TECHNICAL_RESEARCH_TRIGGER"
    assert "WebSocket" in tech_res["specification_guidance"]
