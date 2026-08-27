# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Market Intelligence & Prediction Oversight."""

import pytest

from friday.alert_manager import ProductionAlertManager
from friday.memory.in_memory import InMemoryConversationMemory
from friday.operators.intelligence_vigilance import IntelligenceVigilanceOperator
from friday.skills.intelligence_briefing import IntelligenceBriefingSkill
from friday.skills.registry import SkillRegistry
from friday.trading.intelligence_engine import IntelligenceEngine
from friday.workflows.intel_briefing import MorningIntelligenceBriefingWorkflow


@pytest.fixture
def intel_setup():
    memory = InMemoryConversationMemory()
    alert_mgr = ProductionAlertManager(memory=memory)
    intel_engine = IntelligenceEngine()
    operator = IntelligenceVigilanceOperator(
        intelligence_engine=intel_engine,
        alert_manager=alert_mgr,
        memory=memory,
    )
    skill = IntelligenceBriefingSkill(intelligence_engine=intel_engine)
    briefing_wf = MorningIntelligenceBriefingWorkflow(intelligence_engine=intel_engine)

    return skill, intel_engine, operator, briefing_wf, alert_mgr


# =========================================================================
# 1. Intelligence Engine Tests
# =========================================================================

def test_intelligence_engine_predictions_and_accuracy(intel_setup):
    """Verify prediction fetching, alternative data, and calibration reports."""
    skill, engine, operator, briefing_wf, alert_mgr = intel_setup

    btc = engine.get_prediction("BTCUSDT")
    assert btc is not None
    assert btc.direction == "BULLISH"
    assert btc.direction_probability_pct >= 70.0

    eth = engine.get_prediction("ETHUSDT")
    assert eth is not None
    assert eth.direction == "BEARISH"

    report = engine.get_market_intelligence_report()
    assert "predictions" in report
    assert "sentiment" in report
    assert "on_chain" in report
    assert report["sentiment"]["fear_and_greed_index"] == 68

    acc = engine.get_accuracy_report()
    assert acc.rolling_30d_directional_accuracy_pct >= 70.0
    assert acc.calibration_status == "WELL_CALIBRATED"


# =========================================================================
# 2. Intelligence Vigilance Operator Tests
# =========================================================================

def test_intelligence_vigilance_operator_alerts(intel_setup):
    """Verify vigilance operator alerts on adverse predictions, sentiment, and whale flows."""
    skill, engine, operator, briefing_wf, alert_mgr = intel_setup

    events = operator.tick()
    assert isinstance(events, list)

    types = [e["type"] for e in events]
    assert "ADVERSE_PREDICTION_ALERT" in types
    assert "SENTIMENT_ELEVATION_ALERT" in types
    assert "WHALE_FLOW_ALERT" in types


# =========================================================================
# 3. Voice Intelligence Briefing Commands
# =========================================================================

def test_voice_intelligence_briefing_commands(intel_setup):
    """Verify voice queries for market intelligence, asset predictions, and accuracy."""
    skill, engine, operator, briefing_wf, alert_mgr = intel_setup

    # 1. "Market intelligence report"
    res1 = skill.execute("Market intelligence report")
    assert res1.success is True
    assert "Market intelligence summary:" in res1.output

    # 2. "What does the model predict for BTC?"
    res2 = skill.execute("What does the model predict for BTC?")
    assert res2.success is True
    assert "Prediction for BTCUSDT: The model is 76% BULLISH" in res2.output

    # 3. "What does the model predict for ETH?"
    res3 = skill.execute("What does the model predict for ETH?")
    assert res3.success is True
    assert "Prediction for ETHUSDT: The model is 58% BEARISH" in res3.output

    # 4. "How accurate have predictions been?"
    res4 = skill.execute("How accurate have predictions been?")
    assert res4.success is True
    assert "Prediction accuracy report:" in res4.output
    assert "78.5% directional accuracy" in res4.output

    # 5. "Any intelligence alerts?"
    res5 = skill.execute("Any intelligence alerts?")
    assert res5.success is True
    assert "active market intelligence alerts:" in res5.output


# =========================================================================
# 4. Morning Intelligence Briefing Workflow
# =========================================================================

def test_morning_intelligence_briefing_workflow(intel_setup):
    """Verify MorningIntelligenceBriefingWorkflow generates spoken text and Markdown."""
    skill, engine, operator, briefing_wf, alert_mgr = intel_setup

    assert briefing_wf.can_handle("Give me the morning intelligence briefing") is True

    snapshot = briefing_wf.generate_briefing()
    assert "Good morning Operator Surendra" in snapshot.spoken_briefing
    assert "# 🧠 FRIDAY Morning Market Intelligence Briefing" in snapshot.markdown_report
    assert snapshot.fear_and_greed_index == 68
    assert snapshot.btc_probability_pct == 76.0


def test_intelligence_briefing_registered_in_registry():
    """Verify IntelligenceBriefingSkill is registered in SkillRegistry."""
    reg = SkillRegistry()
    reg.load_builtins()

    skill = reg.get("intelligence_briefing")
    assert skill is not None
    assert "network_access" in skill.required_capabilities
