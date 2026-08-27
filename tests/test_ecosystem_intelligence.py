# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Unified Ecosystem Intelligence Reporting."""

import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
import pytest

from friday.ecosystem.intelligence_service import EcosystemIntelligenceService, EcosystemReport
from friday.ecosystem.registry import EcosystemRegistry, SubsystemEntry
from friday.operators.ecosystem_anomaly_operator import EcosystemAnomalyDetection
from friday.skills.conversational_ecosystem import ConversationalEcosystemQuery
from friday.skills.registry import skill_registry
from friday.ui.intelligence_panel import UnifiedIntelligencePanel


@pytest.fixture
def intelligence_setup():
    temp_dir = tempfile.mkdtemp()
    registry = EcosystemRegistry()
    service = EcosystemIntelligenceService(registry=registry, reports_dir=temp_dir)
    query_skill = ConversationalEcosystemQuery(intelligence_service=service, registry=registry)
    anomaly_op = EcosystemAnomalyDetection(registry=registry, poll_interval_sec=60.0)
    panel = UnifiedIntelligencePanel(intelligence_service=service, registry=registry)

    yield service, query_skill, anomaly_op, panel, registry, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


# =========================================================================
# 1. Ecosystem Intelligence Service Tests
# =========================================================================

def test_intelligence_service_reports_and_retention(intelligence_setup):
    """Verify Morning, Evening, and Weekly reports generation and 90-day retention."""
    service, query_skill, anomaly_op, panel, registry, temp_dir = intelligence_setup

    # 1. Morning Briefing
    morning = service.generate_morning_briefing()
    assert morning.report_type == "MORNING_BRIEFING"
    assert morning.composite_health_score >= 80.0
    assert "Trading Bot is RUNNING" in morning.spoken_summary
    assert "Nexus reports 4,280 website visitors" in morning.spoken_summary

    # 2. Evening Wrap-Up
    evening = service.generate_evening_wrapup()
    assert evening.report_type == "EVENING_WRAPUP"
    assert "profit of +$420.50" in evening.spoken_summary
    assert "Tomorrow's operational outlook is positive" in evening.spoken_summary

    # 3. Weekly Report
    weekly = service.generate_weekly_report()
    assert weekly.report_type == "WEEKLY_REPORT"
    assert "Weekly trading profit reached +$2,450.00" in weekly.spoken_summary
    assert "Strategic Recommendations for Next Week" in weekly.markdown_report

    # 4. Check disk files exist
    files = os.listdir(temp_dir)
    assert len(files) >= 6  # 3 JSON + 3 MD

    # 5. Test 90-day retention pruning
    old_file = os.path.join(temp_dir, "2025-01-01_morning_old.json")
    with open(old_file, "w") as f:
        f.write("{}")
    # Backdate mtime by 100 days
    past_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
    os.utime(old_file, (past_time, past_time))

    pruned = service._prune_90_day_retention()
    assert pruned >= 1
    assert not os.path.exists(old_file)


# =========================================================================
# 2. Conversational Ecosystem Query Skill Tests
# =========================================================================

def test_conversational_ecosystem_queries(intelligence_setup):
    """Verify natural language single and multi-part queries across all 4 subsystems."""
    service, query_skill, anomaly_op, panel, registry, temp_dir = intelligence_setup

    # 1. Nexus query
    res_web = query_skill.execute("How did the website do today?")
    assert res_web.success is True
    assert "4,280 visitors" in res_web.output
    assert "14 high-intent leads" in res_web.output

    # 2. Trading query
    res_trade = query_skill.execute("What did the trading bot decide overnight?")
    assert res_trade.success is True
    assert "3 active positions" in res_trade.output
    assert "+$420.50 USDT" in res_trade.output

    # 3. FORGE query
    res_forge = query_skill.execute("What did Forge build this week?")
    assert res_forge.success is True
    assert "completed 2 production software builds" in res_forge.output

    # 4. Health check
    res_health = query_skill.execute("Is everything healthy?")
    assert res_health.success is True
    assert "All systems are **HEALTHY**" in res_health.output

    # 5. Multi-part cross-subsystem comparison
    res_comp = query_skill.execute("Compare website leads to trading profits this week")
    assert res_comp.success is True
    assert "Nexus generated 14 high-intent enterprise leads" in res_comp.output
    assert "+$420.50 USDT today" in res_comp.output


# =========================================================================
# 3. Ecosystem Anomaly Detection Operator Tests
# =========================================================================

def test_ecosystem_anomaly_detection_rules(intelligence_setup):
    """Verify cross-system anomaly rules: cascading failures, correlated build/AI, quietness."""
    service, query_skill, anomaly_op, panel, registry, temp_dir = intelligence_setup

    # 1. Nominal tick (no anomalies)
    nominal_events = anomaly_op.tick()
    assert len(nominal_events) == 0

    # 2. Cascading Failure Simulation
    custom_reg = EcosystemRegistry()
    custom_reg.register(SubsystemEntry("trading_bot", "Trading Bot", "trading", "📈", lambda: {}, lambda: {"status": "CRITICAL"}))
    custom_reg.register(SubsystemEntry("nexus", "Nexus", "growth", "🌐", lambda: {}, lambda: {"status": "DEGRADED"}))
    custom_reg.register(SubsystemEntry("forge", "Forge", "engineering", "🛠️", lambda: {}, lambda: {"status": "HEALTHY"}))
    custom_reg.register(SubsystemEntry("ai_universe", "AI-Universe", "intelligence", "🧠", lambda: {}, lambda: {"status": "HEALTHY"}))

    cascade_op = EcosystemAnomalyDetection(registry=custom_reg)
    events = cascade_op.tick()
    assert any(e["type"] == "CASCADING_FAILURE" for e in events)

    # 3. Correlated Build / AI Failure Simulation
    custom_reg2 = EcosystemRegistry()
    custom_reg2.register(SubsystemEntry("trading_bot", "Trading Bot", "trading", "📈", lambda: {}, lambda: {"status": "RUNNING"}))
    custom_reg2.register(SubsystemEntry("nexus", "Nexus", "growth", "🌐", lambda: {}, lambda: {"status": "HEALTHY"}))
    custom_reg2.register(SubsystemEntry("forge", "Forge", "engineering", "🛠️", lambda: {}, lambda: {"status": "FAILED"}))
    custom_reg2.register(SubsystemEntry("ai_universe", "AI-Universe", "intelligence", "🧠", lambda: {}, lambda: {"status": "DEGRADED"}))

    correlated_op = EcosystemAnomalyDetection(registry=custom_reg2)
    events2 = correlated_op.tick()
    assert any(e["type"] == "CORRELATED_BUILD_AI_FAILURE" for e in events2)


# =========================================================================
# 4. Unified Intelligence Panel & Skill Registry Tests
# =========================================================================

def test_unified_intelligence_panel_and_registration(intelligence_setup):
    """Verify panel assembly, markdown presentation, and skill registration."""
    service, query_skill, anomaly_op, panel, registry, temp_dir = intelligence_setup

    data = panel.render_intelligence_data()
    assert data["composite_health_score"] >= 80.0
    assert "trading" in data["subsystems"]
    assert "nexus" in data["subsystems"]
    assert "forge" in data["subsystems"]
    assert "ai_universe" in data["subsystems"]

    md = panel.render_markdown()
    assert "Composite Ecosystem Health" in md
    assert "Nexus Growth & Website" in md

    # Skill Registry
    assert any(s.name == "conversational_ecosystem" for s in skill_registry.list_skills())
    assert skill_registry.get("conversational_ecosystem") is not None
