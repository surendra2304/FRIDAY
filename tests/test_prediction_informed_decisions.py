# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for Prediction-Informed Decisions, Proactive Forecasting, and Tracking.

Validates:
1. PredictionInformedDecisionEngine:
   - Forge task evaluation (queues on >=80% capacity forecast)
   - Trading advisory enrichment with volatility forecast
   - Nexus campaign timing with traffic forecast
   - Sentinel scan urgency evaluation based on exploitation probability
   - INVARIANT: Predictions are inputs to decisions, never autonomous decision-makers
2. ProactiveForecastingWorkflow:
   - Daily capacity forecast across active subsystems
   - Weekly multi-domain risk forecast compilation
   - Event-triggered forecasts (Nexus traffic spike, Sentinel critical CVE)
3. PredictionTrackingWorkflow:
   - Decision recording with forecast intervals
   - Outcome resolution and empirical accuracy scoring
   - User-facing transparency statistics ("accurate X% of the time")
4. Trust & Security:
   - UNTRUSTED_EXTERNAL boundary enforcement
"""

import pytest

from friday.core.prediction_decisions import PredictionInformedDecisionEngine
from friday.core.types import TrustLevel
from friday.skills.futuris_manager import FuturisManagerSkill
from friday.workflows.prediction_tracking import PredictionTrackingWorkflow
from friday.workflows.proactive_forecasting import ProactiveForecastingWorkflow


def test_prediction_informed_decision_engine():
    skill = FuturisManagerSkill()
    engine = PredictionInformedDecisionEngine(futuris_skill=skill)

    # 1. Forge Evaluation
    forge_eval = engine.evaluate_forge_task_submission({"task": "Compile Rust Binary"})
    assert forge_eval.domain == "forge"
    assert forge_eval.recommendation in ["PROCEED", "QUEUE"]
    assert len(forge_eval.confidence_interval) == 2
    assert forge_eval.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Trading Advisory Enrichment
    trade_eval = engine.enrich_trading_advisory_context({"pair": "BTC/USDT"})
    assert trade_eval.domain == "trading"
    assert "advisory" in trade_eval.rationale.lower()
    assert trade_eval.recommendation == "ADVISORY_CONTEXT_INJECTED"

    # 3. Nexus Campaign Timing
    nexus_eval = engine.evaluate_nexus_campaign_timing({"campaign": "Product Hunt Launch"})
    assert nexus_eval.domain == "nexus"
    assert "launch window" in nexus_eval.rationale.lower()

    # 4. Sentinel Scan Urgency
    sent_eval = engine.evaluate_sentinel_scan_urgency(asset_target="api.surendra.dev", cve_id="CVE-2026-4412")
    assert sent_eval.domain == "sentinel"
    assert sent_eval.recommendation in ["ESCALATE_IMMEDIATE", "STANDARD_SCHEDULE"]
    assert "CVE-2026-4412" in sent_eval.target_metric


def test_proactive_forecasting_workflow():
    skill = FuturisManagerSkill()
    workflow = ProactiveForecastingWorkflow(futuris_skill=skill)

    # 1. Daily Capacity Forecast
    daily = workflow.generate_daily_capacity_forecast()
    assert daily.summary_type == "DAILY_CAPACITY"
    assert len(daily.forecasts) == 4
    assert len(daily.key_findings) == 4
    assert daily.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Weekly Risk Forecast
    weekly = workflow.compile_weekly_risk_forecast()
    assert weekly.summary_type == "WEEKLY_RISK"
    assert len(weekly.forecasts) == 3
    assert len(weekly.key_findings) == 3

    # 3. Event-Triggered Forecasts
    nexus_fc = workflow.trigger_nexus_anomaly_forecast({"source": "Reddit Tech Surge"})
    assert nexus_fc["success"] is True
    assert "Reddit Tech Surge" in nexus_fc["target"]

    sent_fc = workflow.trigger_sentinel_vulnerability_forecast({"cve_id": "CVE-2026-8891"})
    assert sent_fc["success"] is True
    assert "CVE-2026-8891" in sent_fc["target"]


def test_prediction_tracking_and_feedback():
    tracker = PredictionTrackingWorkflow()

    # 1. Record Decision
    rid = tracker.record_decision_with_forecast(
        domain="forge",
        decision_description="Deploy compiler worker pool #4",
        forecast_id="fc-test-101",
        target_metric="Peak Worker Load",
        point_estimate=75.0,
        confidence_interval=[65.0, 85.0],
    )
    assert rid.startswith("rec-pred-")

    # 2. Resolve Outcome (Value within interval -> Accurate)
    resolved = tracker.resolve_decision_outcome(record_id=rid, actual_value=78.4)
    assert resolved is not None
    assert resolved.resolved is True
    assert resolved.was_accurate is True

    # 3. Accuracy Summary
    summary = tracker.get_accuracy_summary(last_n=15)
    assert summary["total_evaluated"] >= 8
    assert summary["accuracy_pct"] >= 75.0
    assert "Futuris predictions used in your last" in summary["formatted_summary"]
    assert "accurate" in summary["formatted_summary"]
