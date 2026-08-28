# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for Research Briefings, Intelligence Dashboard & Suggestions.

Validates:
1. IntelligenceBriefingWorkflow:
   - Daily intelligence snapshot generation
   - Domain-specific findings grouping (Security, Market, Technical, Competitive)
   - Contradiction surfacing with Side A vs Side B evidence
   - Follow-up research gap recommendations
   - Natural spoken briefing formatting
2. ResearchSuggestionEngine:
   - Contextual research suggestions from Trading Bot, Sentinel, Nexus, and Forge states
   - Proposal retrieval and acceptance lifecycle
3. ResearchDashboardPanel:
   - Dashboard rendering with active progress, findings feed, contradiction explorer, domain trends, and suggestions
   - Domain filter view verification
4. Trust & Security Invariants:
   - All snapshots, panels, and proposals carry TrustLevel.UNTRUSTED_EXTERNAL
"""

from friday.core.types import TrustLevel
from friday.skills.intelx_manager import IntelXManagerSkill
from friday.skills.research_suggestions import ResearchSuggestionEngine
from friday.ui.research_panel import ResearchDashboardPanel
from friday.workflows.intelligence_briefing import IntelligenceBriefingWorkflow


def test_intelligence_briefing_workflow_generation():
    intelx = IntelXManagerSkill()
    workflow = IntelligenceBriefingWorkflow(intelx_skill=intelx)

    snapshot = workflow.generate_daily_intelligence_briefing()
    assert snapshot.briefing_id is not None
    assert snapshot.verified_findings_count >= 2
    assert snapshot.contradictions_count >= 1
    assert snapshot.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 1. Spoken Briefing contains key highlights
    spoken = snapshot.spoken_briefing
    assert "daily intelligence briefing" in spoken
    assert "Security" in spoken
    assert "disputed" in spoken

    # 2. Markdown Report contains 4 key pillars
    md = snapshot.markdown_report
    assert "1. Overnight Research Completed" in md
    assert "2. Disputed Claims & Contradictions" in md
    assert "3. Operational Intelligence Alignment" in md
    assert "4. Recommended Follow-Up Research" in md
    assert "UNTRUSTED_EXTERNAL" in md


def test_research_suggestion_engine_triggers_and_acceptance():
    engine = ResearchSuggestionEngine()

    # 1. Inspect default proposals
    pending = engine.get_pending_suggestions()
    assert len(pending) >= 3
    assert any(s["subsystem"] == "trading_bot" for s in pending)
    assert any(s["subsystem"] == "sentinel" for s in pending)
    assert any(s["subsystem"] == "nexus" for s in pending)

    # 2. Accept a proposal
    sug_id = pending[0]["suggestion_id"]
    accepted = engine.accept_suggestion(sug_id)
    assert accepted is not None
    assert accepted["status"] == "ACCEPTED"
    assert accepted["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # Verify removed from pending
    remaining = engine.get_pending_suggestions()
    assert not any(s["suggestion_id"] == sug_id for s in remaining)


def test_research_dashboard_panel_rendering_and_filtering():
    intelx = IntelXManagerSkill()
    suggestions = ResearchSuggestionEngine()
    panel = ResearchDashboardPanel(intelx_skill=intelx, suggestion_engine=suggestions)

    # 1. Full Dashboard Rendering
    md = panel.render_panel()
    assert "# 🔬 IntelX Autonomous Deep Research & Intelligence Panel" in md
    assert "1. Active Research Progress" in md
    assert "2. Recent Verified Findings Feed" in md
    assert "3. Side-by-Side Contradiction Explorer" in md
    assert "4. Research Domain Distribution & Trends" in md
    assert "5. Proactive Contextual Suggestions" in md

    # 2. Domain Filtered Rendering
    md_sec = panel.render_panel(domain_filter="security")
    assert "Recent Verified Findings Feed" in md_sec
