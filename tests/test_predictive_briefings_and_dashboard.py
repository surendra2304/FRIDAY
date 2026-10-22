"""Comprehensive Test Suite for Predictive Briefings and Ecosystem Forecast Dashboard.

Validates:
1. PredictiveBriefingWorkflow:
   - Daily predictive briefing generation with spoken summary and markdown report
   - Multi-system outlook (Nexus traffic, Forge capacity, Trading volatility)
   - 48-hour probability-weighted risk horizon
   - Opportunity signals
   - Weekly predictive review compilation with per-system breakdown
2. Natural Voice Commands:
   - "What's the forecast for tomorrow?"
   - "What risks are coming?"
   - "How reliable are these predictions?"
3. EcosystemForecastDashboard:
   - Full dashboard rendering
   - Active forecast tables, risk heatmap, scenario explorer, and calibration matrix
4. Trust & Security Invariants:
   - Predictions always presented with explicit confidence intervals
   - Tagged TrustLevel.UNTRUSTED_EXTERNAL
"""


from friday.core.types import TrustLevel
from friday.skills.futuris_manager import FuturisManagerSkill
from friday.ui.forecast_panel import EcosystemForecastDashboard
from friday.workflows.predictive_briefing import PredictiveBriefingWorkflow


def test_daily_predictive_briefing_generation():
    skill = FuturisManagerSkill()
    workflow = PredictiveBriefingWorkflow(futuris_skill=skill)

    snapshot = workflow.generate_daily_predictive_briefing()
    assert snapshot.briefing_type == "DAILY_PREDICTIVE"
    assert snapshot.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # Spoken summary contains outlook, risk, calibration
    spoken = snapshot.spoken_summary
    assert "Nexus traffic at" in spoken
    assert "Forge load at" in spoken
    assert "market volatility at" in spoken
    assert "CI]" in spoken  # Uncertainty interval
    assert "Brier score" in spoken

    # Markdown report contains structured sections
    md = snapshot.markdown_report
    assert "1. Tomorrow's Multi-System Outlook" in md
    assert "2. 48-Hour Probability-Weighted Risk Horizon" in md
    assert "3. Forecasted Opportunity Signals" in md
    assert "4. Predictive Calibration & Reliability Audit" in md


def test_weekly_predictive_review_compilation():
    skill = FuturisManagerSkill()
    workflow = PredictiveBriefingWorkflow(futuris_skill=skill)

    review = workflow.generate_weekly_predictive_review()
    assert review["period"] == "Past 7 Days"
    assert review["overall_accuracy_pct"] >= 80.0
    assert "forge" in review["breakdown_by_system"]
    assert "nexus" in review["breakdown_by_system"]
    assert "trading_bot" in review["breakdown_by_system"]
    assert "sentinel" in review["breakdown_by_system"]
    assert len(review["upcoming_week_forecast"]) >= 2


def test_predictive_voice_queries():
    skill = FuturisManagerSkill()
    workflow = PredictiveBriefingWorkflow(futuris_skill=skill)

    # 1. "What's the forecast for tomorrow?"
    res_tomorrow = workflow.execute_voice_query("What's the forecast for tomorrow?")
    assert "Nexus traffic at" in res_tomorrow
    assert "CI]" in res_tomorrow

    # 2. "What risks are coming?"
    res_risks = workflow.execute_voice_query("What risks are coming?")
    assert "Probability-Weighted Risks:" in res_risks
    assert "Checkout Capacity Saturation" in res_risks
    assert "CI]" in res_risks

    # 3. "How reliable are these predictions?"
    res_rel = workflow.execute_voice_query("How reliable are these predictions?")
    assert "Brier score" in res_rel
    assert "confidence intervals" in res_rel


def test_ecosystem_forecast_dashboard_rendering():
    skill = FuturisManagerSkill()
    dashboard = EcosystemForecastDashboard(futuris_skill=skill)

    view = dashboard.render_full_dashboard()
    assert "FRIDAY Ecosystem Probabilistic Forecast Dashboard" in view
    assert "1. Active Forecasts & Uncertainty Intervals" in view
    assert "2. Probability-Weighted Multi-System Risk Heatmap" in view
    assert "3. Counterfactual Scenario Explorer" in view
    assert "4. Domain Calibration Matrix & Key Drivers" in view
    assert "Brier Score" in view
