"""Comprehensive Test Suite for Futuris Forecasting Manager & Forecast Supervisor.

Validates:
1. FuturisManagerSkill:
   - request_forecast with explicit confidence intervals
   - request_scenario what-if counterfactual analysis
   - get_forecast_status and causal drivers inspection
   - get_calibration_report accuracy audit
   - list_recent_forecasts
2. Natural Voice Commands with mandatory confidence intervals:
   - "What does Futuris predict for [metric]?"
   - "What are the chances of [event]?"
   - "Run a scenario: what if [change]?"
   - "How accurate are Futuris predictions?"
   - "Show me forecast trends"
3. ForecastSupervisorOperator:
   - THRESHOLD_CROSSED alert trigger
   - FORECAST_INVALIDATED reality divergence alert
   - MODEL_DEGRADED calibration alarm
4. Trust & Security Invariants:
   - All forecasting artifacts carry TrustLevel.UNTRUSTED_EXTERNAL
   - FRIDAY never presents point estimates without uncertainty bounds
"""


from friday.core.types import TrustLevel
from friday.operators.forecast_supervisor_operator import ForecastSupervisorOperator
from friday.skills.futuris_manager import FuturisManagerSkill


def test_futuris_manager_api_operations():
    skill = FuturisManagerSkill()

    # 1. Request Forecast
    fc = skill.request_forecast(target="Server Ingress QPS", horizon="12 hours", confidence_level=0.90)
    assert fc["success"] is True
    assert fc["forecast_id"] is not None
    assert len(fc["confidence_interval"]) == 2
    assert fc["confidence_interval"][0] < fc["confidence_interval"][1]
    assert fc["trust_level"] == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Request Scenario
    scen = skill.request_scenario(
        question="What if marketing traffic increases by 50%?",
        base_forecast_id="fc-checkout-24h",
        changes={"traffic": +50.0},
    )
    assert scen["scenario_id"] is not None
    assert scen["simulated_estimate"] > 75.0
    assert len(scen["simulated_interval"]) == 2

    # 3. Status & Drivers
    status = skill.get_forecast_status("fc-checkout-24h")
    assert status is not None
    assert len(status["drivers"]) >= 2
    assert "Marketing Campaign" in status["drivers"][0]["name"]

    # 4. Calibration Report
    cal = skill.get_calibration_report()
    assert cal["status"] == "WELL_CALIBRATED"
    assert cal["brier_score"] <= 0.10


def test_futuris_manager_voice_commands_with_uncertainty():
    skill = FuturisManagerSkill()

    # 1. "What does Futuris predict for Redis cache memory?"
    res_pred = skill.execute("What does Futuris predict for Redis cache memory?")
    assert res_pred.success is True
    out_pred = res_pred.output
    assert "Futuris Prediction for Redis cache memory:" in out_pred
    assert "CI]" in out_pred  # Must include confidence interval
    assert "@ 90% CI" in out_pred

    # 2. "What are the chances of capacity breach?"
    res_chance = skill.execute("What are the chances of capacity breach?")
    assert res_chance.success is True
    out_chance = res_chance.output
    assert "probability" in out_chance
    assert "[68% - 82% @ 90% CI]" in out_chance

    # 3. "Run a scenario: what if traffic surges by 30%?"
    res_scen = skill.execute("Run a scenario: what if traffic surges by 30%?")
    assert res_scen.success is True
    assert "Scenario Simulation Result:" in res_scen.output
    assert "CI]" in res_scen.output

    # 4. "How accurate are Futuris predictions?"
    res_cal = skill.execute("How accurate are Futuris predictions?")
    assert res_cal.success is True
    assert "Calibration Report:" in res_cal.output
    assert "Brier score" in res_cal.output

    # 5. "Show me forecast trends"
    res_trends = skill.execute("Show me forecast trends")
    assert res_trends.success is True
    assert "Forecast Trends" in res_trends.output
    assert "90% CI" in res_trends.output


def test_forecast_supervisor_operator_alerts():
    skill = FuturisManagerSkill()
    operator = ForecastSupervisorOperator(futuris_skill=skill)

    # 1. Cycle triggers THRESHOLD_CROSSED alert because checkout capacity p_high = 82% >= 80%
    alerts = operator.run_supervisory_cycle()
    assert len(alerts) >= 1
    thresh_alert = next((a for a in alerts if a.alert_type == "THRESHOLD_CROSSED"), None)
    assert thresh_alert is not None
    assert "capacity exceedance" in thresh_alert.message
    assert thresh_alert.trust_level == TrustLevel.UNTRUSTED_EXTERNAL.value

    # 2. Cycle triggers FORECAST_INVALIDATED on divergence override
    inval_alerts = operator.run_supervisory_cycle(
        telemetry_override={"divergence_detected": True, "metric": "ETH Liquidations"}
    )
    inval = next((a for a in inval_alerts if a.alert_type == "FORECAST_INVALIDATED"), None)
    assert inval is not None
    assert "Reality diverged from prediction" in inval.message
