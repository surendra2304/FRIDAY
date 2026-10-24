"""
FRIDAY/apps/core/src/friday_core/real_deep_api_server.py — Deep API Server.

Real HTTP API server exposing deep engines across all agents:
- Cortex deep endpoints: /api/deep/recommend, /api/deep/predict, /api/deep/foresight
- Stratex deep endpoints: /api/deep/sentiment, /api/deep/orderflow, /api/deep/patterns
- Forge deep endpoints: /api/deep/security-scan, /api/deep/deps, /api/deep/refactor
- Sentinel deep endpoints: /api/deep/vuln-mgmt, /api/deep/compliance, /api/deep/incidents
- IntelX deep endpoints: /api/deep/threat-forecast, /api/deep/intel-quality, /api/deep/disinfo
- Futuris deep endpoints: /api/deep/ensemble, /api/deep/forecast, /api/deep/stress
- VyralX deep endpoints: /api/deep/audience, /api/deep/growth, /api/deep/moderation
- Cross-agent deep workflows
"""
from __future__ import annotations

import json
import os
import sys
import importlib.util
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent

# Load deep engine modules
def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

cortex_deep = _load("deep_cortex_api", "Cortex/apps/api/src/cortex_api/real_deep_engines.py")
stratex_deep = _load("deep_stratex_api", "Stratex/real_deep_trading.py")
forge_deep = _load("deep_forge_api", "Forge/app/services/real_deep_code.py")
sentinel_deep = _load("deep_sentinel_api", "Sentinel/app/services/real_deep_security.py")
intelx_deep = _load("deep_intelx_api", "IntelX/intelx/services/real_deep_threat_intel.py")
futuris_deep = _load("deep_futuris_api", "Futuris/futuris/core/real_deep_forecast.py")
vyralx_deep = _load("deep_vyralx_api", "VyralX/app/services/real_deep_content.py")

app = FastAPI(title="FRIDAY Universe Deep API", version="3.0.0",
              description="Deep layer-3 engines across all agents")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# Request models
class RecommendRequest(BaseModel):
    user_id: str
    item_features: dict[str, dict[str, float]] = {}
    item_interactions: dict[str, list[str]] = {}


class PredictRequest(BaseModel):
    model_id: str
    features: dict[str, float]
    training_data: list[dict] = []
    targets: list[float] = []


class ForesightRequest(BaseModel):
    topic: str
    factors: list[str]


class SentimentRequest(BaseModel):
    symbol: str
    text: str


class OrderFlowRequest(BaseModel):
    symbol: str
    trades: list[dict]


class PatternRequest(BaseModel):
    symbol: str
    prices: list[float]


class CodeScanRequest(BaseModel):
    code: str
    filename: str = "unknown"


class DepsRequest(BaseModel):
    requirements: dict[str, str]


class RefactorRequest(BaseModel):
    code: str
    filename: str = "unknown"


class VulnMgmtRequest(BaseModel):
    cve_id: str
    severity: str
    name: str
    description: str
    score: float
    component: str


class ComplianceRequest(BaseModel):
    framework: str


class IncidentRequest(BaseModel):
    incident_type: str


class ThreatForecastRequest(BaseModel):
    threat_type: str
    history: list[dict]


class IntelQualityRequest(BaseModel):
    source_id: str
    indicators: list[dict]
    feedback: list[dict] = []


class DisinfoRequest(BaseModel):
    text: str


class EnsembleRequest(BaseModel):
    model_forecasts: dict[str, float]
    weights: dict[str, float]


class ForecastDeepRequest(BaseModel):
    series: list[float]
    method: str = "auto"
    horizon: int = 10


class StressRequest(BaseModel):
    baseline: float
    scenarios: list[dict] = []


class AudienceRequest(BaseModel):
    viewers: list[dict]


class GrowthRequest(BaseModel):
    channel_stats: dict


class ModerationRequest(BaseModel):
    content_id: str
    text: str


# Cortex Deep Endpoints
@app.post("/api/deep/recommend")
def deep_recommend(req: RecommendRequest):
    engine = cortex_deep.RecommendationPersonalizer()
    for item, features in req.item_features.items():
        engine.add_item_features(item, features)
    for user, items in req.item_interactions.items():
        for item in items:
            engine.record_interaction(user, item)
    recs = engine.recommend_collaborative(req.user_id, top_k=5)
    return {"user_id": req.user_id, "recommendations": [r.item_id for r in recs],
            "scores": [r.score for r in recs]}


@app.post("/api/deep/predict")
def deep_predict(req: PredictRequest):
    engine = cortex_deep.PredictiveAnalyticsEngine()
    if req.training_data and req.targets:
        coefs = engine.train_linear_regression(req.model_id, req.training_data, req.targets)
    prediction = engine.predict(req.model_id, req.features)
    return {"model_id": req.model_id, "prediction": prediction.prediction,
            "confidence": prediction.confidence, "method": prediction.method}


@app.post("/api/deep/foresight")
def deep_foresight(req: ForesightRequest):
    scenarios = cortex_deep.foresight.generate_scenarios(req.topic, req.factors)
    return {"topic": req.topic, "scenarios": [
        {"name": s.name, "probabilities": s.probabilities,
         "actions": s.preparation_actions} for s in scenarios
    ]}


# Stratex Deep Endpoints
@app.post("/api/deep/sentiment")
def deep_sentiment(req: SentimentRequest):
    result = stratex_deep.sentiment_engine.analyze(req.symbol, req.text)
    return {"symbol": req.symbol, "score": result.sentiment_score,
            "sentiment": result.dominant_sentiment, "confidence": result.confidence,
            "top_words": result.top_words}


@app.post("/api/deep/orderflow")
def deep_orderflow(req: OrderFlowRequest):
    result = stratex_deep.order_flow.analyze(req.symbol, req.trades)
    return {"symbol": req.symbol, "imbalance": result.imbalance,
            "signal": result.signal, "flow_ratio": result.flow_ratio}


@app.post("/api/deep/patterns")
def deep_patterns(req: PatternRequest):
    patterns = stratex_deep.pattern_engine.detect_patterns(req.symbol, req.prices)
    return {"symbol": req.symbol, "patterns": [
        {"name": p.pattern, "confidence": p.confidence,
         "breakout": p.breakout_level, "target": p.target_price,
         "stop_loss": p.stop_loss_price} for p in patterns
    ]}


# Forge Deep Endpoints
@app.post("/api/deep/security-scan")
def deep_security_scan(req: CodeScanRequest):
    findings = forge_deep.security_scanner.scan(req.code, req.filename)
    return {"filename": req.filename, "findings": [
        {"rule": f.rule, "line": f.line, "severity": f.severity,
         "cwe": f.cwe, "description": f.description, "remediation": f.remediation}
        for f in findings
    ], "summary": forge_deep.security_scanner.get_summary(findings)}


@app.post("/api/deep/deps")
def deep_deps(req: DepsRequest):
    result = forge_deep.dependency_analyzer.analyze(req.requirements)
    return {"total": result.total_dependencies,
            "vulnerable": [{"name": d.name, "version": d.version,
                          "issue": d.issue} for d in result.vulnerable_dependencies],
            "outdated": [{"name": d.name, "version": d.version,
                          "latest": d.latest_version} for d in result.outdated_dependencies]}


@app.post("/api/deep/refactor")
def deep_refactor(req: RefactorRequest):
    suggestions = forge_deep.refactoring_engine.analyze(req.code, req.filename)
    return {"filename": req.filename, "suggestions": [
        {"type": s.type, "line": s.line, "message": s.message,
         "severity": s.severity} for s in suggestions
    ], "count": len(suggestions)}


# Sentinel Deep Endpoints
@app.post("/api/deep/vuln-mgmt")
def deep_vuln_mgmt(req: VulnMgmtRequest):
    engine = sentinel_deep.VulnerabilityManagementSystem()
    vuln = engine.add_vulnerability(req.cve_id, req.severity, req.name,
                                     req.description, req.score, req.component)
    summary = engine.get_vulnerability_summary()
    return {"vulnerability": vuln.vuln_id, "summary": summary}


@app.post("/api/deep/compliance")
def deep_compliance(req: ComplianceRequest):
    checks = sentinel_deep.compliance_audit.audit(req.framework)
    score = sentinel_deep.compliance_audit.compliance_score(checks)
    return {"framework": req.framework, "score": score, "checks": [
        {"name": c.check_name, "status": c.status,
         "details": c.details, "remediation": c.remediation} for c in checks
    ]}


@app.post("/api/deep/incidents")
def deep_incidents(req: IncidentRequest):
    steps = sentinel_deep.incident_playbook.execute_playbook(req.incident_type)
    return {"incident_type": req.incident_type, "steps": [
        {"name": s.step_name, "status": s.status, "details": s.details} for s in steps
    ]}


# IntelX Deep Endpoints
@app.post("/api/deep/threat-forecast")
def deep_threat_forecast(req: ThreatForecastRequest):
    result = intelx_deep.threat_forecast.forecast(req.threat_type, req.history)
    return {"threat_type": req.threat_type, "probability": result.probability,
            "trend": result.trend, "confidence": result.confidence,
            "indicators": result.indicators}


@app.post("/api/deep/intel-quality")
def deep_intel_quality(req: IntelQualityRequest):
    result = intelx_deep.quality_evaluator.evaluate(req.source_id, req.indicators, req.feedback)
    return {"source_id": req.source_id, "overall": result.overall,
            "grade": result.grade, "scores": {
                "completeness": result.completeness,
                "accuracy": result.accuracy,
                "timeliness": result.timeliness,
                "relevance": result.relevance,
            }}


@app.post("/api/deep/disinfo")
def deep_disinfo(req: DisinfoRequest):
    result = intelx_deep.disinfo_detector.detect(req.text)
    return {"is_disinformation": result.is_disinformation,
            "score": result.fact_check_score,
            "indicators": result.indicators}


# Futuris Deep Endpoints
@app.post("/api/deep/ensemble")
def deep_ensemble(req: EnsembleRequest):
    ensemble, confidence = futuris_deep.ensemble_selector.create_ensemble_forecast(
        req.model_forecasts, req.weights)
    return {"ensemble_forecast": ensemble, "confidence": confidence}


@app.post("/api/deep/forecast")
def deep_forecast(req: ForecastDeepRequest):
    result = futuris_deep.forecasting_engine.forecast(req.series, req.method, req.horizon)
    return {"method": result.method, "forecast": result.forecast_values,
            "mape": result.mape, "intervals": result.confidence_intervals}


@app.post("/api/deep/stress")
def deep_stress(req: StressRequest):
    if req.scenarios:
        results = futuris_deep.stress_tester.run_stress_test(req.baseline, req.scenarios)
    else:
        results = futuris_deep.stress_tester.standard_scenarios(req.baseline)
    return {"baseline": req.baseline, "scenarios": [
        {"name": s.name, "description": s.description,
         "shock_pct": s.shock_pct, "stressed": s.stressed, "impact": s.impact}
        for s in results
    ]}


# VyralX Deep Endpoints
@app.post("/api/deep/audience")
def deep_audience(req: AudienceRequest):
    segments = vyralx_deep.audience_intel.analyze_audience(req.viewers)
    summary = vyralx_deep.audience_intel.get_audience_summary(segments)
    return {"summary": summary, "segments": [
        {"name": s.name, "size": s.size, "interests": s.interests,
         "engagement": s.engagement_rate} for s in segments
    ]}


@app.post("/api/deep/growth")
def deep_growth(req: GrowthRequest):
    strategies = vyralx_deep.growth_strategy.generate_strategies(req.channel_stats)
    recommended = vyralx_deep.growth_strategy.get_recommended_strategy(req.channel_stats, strategies)
    return {"strategies": [
        {"name": s.name, "growth_pct": s.expected_growth_pct,
         "effort": s.effort, "timeline": s.timeline_days} for s in strategies
    ], "recommended": recommended.name}


@app.post("/api/deep/moderation")
def deep_moderation(req: ModerationRequest):
    result = vyralx_deep.moderation_engine.moderate(req.content_id, req.text)
    return {"action": result.action, "reason": result.reason,
            "category": result.category, "confidence": result.confidence}


@app.get("/health/deep")
def health_deep():
    return {"status": "healthy", "engines": 7, "layer": "deep",
            "version": "3.0.0"}
