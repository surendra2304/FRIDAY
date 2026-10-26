"""
FRIDAY/apps/core/src/friday_core/real_api_server.py — Real API Server.

Exposes all real engines as HTTP endpoints using FastAPI:
- POST /api/decision/decide — Make a decision
- POST /api/reasoning/bayesian — Bayesian update
- POST /api/memory/store — Store a memory
- POST /api/memory/search — Search memories
- POST /api/trading/backtest — Run a backtest
- POST /api/trading/signals — Generate signals
- POST /api/code/analyze — Analyze code
- POST /api/security/scan — Scan for threats
- POST /api/threat/correlate — Correlate indicators
- POST /api/forecast/ensemble — Ensemble forecast
- POST /api/content/predict — Predict content performance
- POST /api/workflow/trading — Run trading workflow
- POST /api/workflow/security — Run security workflow
- POST /api/workflow/code — Run code workflow
- POST /api/workflow/content — Run content workflow
- GET /api/status — Universe status

Priority 1: Real HTTP API exposing all working engines
"""
from __future__ import annotations

import importlib.util
import sys
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent


def load_engine(relpath, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load all engines
_cortex = load_engine("Cortex/apps/api/src/cortex_api/real_decision_engine.py", "api_decision")
_inference = load_engine("Inference/app/agents/real_reasoning_engine.py", "api_reasoning")
_memora = load_engine("Memora/core/memory/real_memory_engine.py", "api_memory")
_stratex = load_engine("Stratex/real_trading_engine.py", "api_trading")
_forge = load_engine("Forge/app/services/real_code_engine.py", "api_code")
_sentinel = load_engine("Sentinel/app/services/real_security_engine.py", "api_security")
_intelx = load_engine("IntelX/intelx/services/real_threat_intel_engine.py", "api_threat_intel")
_futuris = load_engine("Futuris/futuris/core/real_forecast_engine.py", "api_forecast")
_vyralx = load_engine("VyralX/app/services/real_content_engine.py", "api_content")
_cross = load_engine("FRIDAY/apps/core/src/friday_core/real_cross_agent_engine.py", "api_cross_agent")

# Load deep layer-3 engines
_cortex_deep = load_engine("Cortex/apps/api/src/cortex_api/real_deep_engines.py", "api_cortex_deep")
_stratex_deep = load_engine("Stratex/real_deep_trading.py", "api_stratex_deep")
_forge_deep = load_engine("Forge/app/services/real_deep_code.py", "api_forge_deep")
_sentinel_deep = load_engine("Sentinel/app/services/real_deep_security.py", "api_sentinel_deep")
_intelx_deep = load_engine("IntelX/intelx/services/real_deep_threat_intel.py", "api_intelx_deep")
_futuris_deep = load_engine("Futuris/futuris/core/real_deep_forecast.py", "api_futuris_deep")
_vyralx_deep = load_engine("VyralX/app/services/real_deep_content.py", "api_vyralx_deep")

# Initialize engines with persistent state
_state_dir = str(ROOT / "FRIDAY" / ".data" / "api_server")
os.makedirs(_state_dir, exist_ok=True)

decision_engine = _cortex.DecisionEngine(state_file=f"{_state_dir}/decisions.json")
reasoning_engine = _inference.ReasoningEngine(state_file=f"{_state_dir}/reasoning.json")
memory_engine = _memora.MemoryEngine(store_dir=f"{_state_dir}/memora")
trading_engine = _stratex.TradingEngine(state_dir=f"{_state_dir}/stratex")
code_engine = _forge.CodeEngine(template_dir=f"{_state_dir}/templates")
security_engine = _sentinel.SecurityEngine(state_dir=f"{_state_dir}/sentinel")
threat_engine = _intelx.ThreatIntelEngine(state_dir=f"{_state_dir}/intelx")
forecast_engine = _futuris.ForecastEngine(state_dir=f"{_state_dir}/futuris")
content_engine = _vyralx.ContentEngine(state_dir=f"{_state_dir}/vyralx")
cross_engine = _cross.CrossAgentEngine(state_dir=_state_dir)

app = FastAPI(title="FRIDAY Universe API", version="2.0.0")

from friday_core.real_research_api import create_research_router
app.include_router(create_research_router(cross_engine))

# CORS for all origins (needed for preview environment)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response Models ────────────────────────────────────────────────

class DecisionRequest(BaseModel):
    question: str
    options: list[dict[str, Any]]
    criteria: list[dict[str, Any]]


class BayesianRequest(BaseModel):
    hypothesis: str
    prior: float
    evidence: str
    likelihood: float


class MemoryStoreRequest(BaseModel):
    content: str
    agent_origin: str = "unknown"
    tags: list[str] = []
    importance: float = 0.5


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 10
    tags: list[str] | None = None


class TradingBacktestRequest(BaseModel):
    symbol: str
    prices: list[float]
    strategy: str = "sma_cross"
    initial_capital: float = 10000.0
    position_size_pct: float = 0.1
    fee_pct: float = 0.001
    slippage_pct: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class CodeAnalyzeRequest(BaseModel):
    code: str
    language: str = "python"


class SecurityScanRequest(BaseModel):
    code: str = ""
    logs: str = ""


class ThreatCorrelateRequest(BaseModel):
    indicators: list[dict[str, Any]]


class ForecastRequest(BaseModel):
    symbol: str
    series: list[float]


class ContentPredictRequest(BaseModel):
    title: str
    description: str
    tags: list[str] = []


class WorkflowRequest(BaseModel):
    strategy: str = "sma_cross"
    symbol: str | None = None
    prices: list[float] | None = None
    code: str | None = None
    logs: str | None = None
    topic: str | None = None


# ── Decision API ────────────────────────────────────────────────────────────

@app.post("/api/decision/decide")
async def decide(req: DecisionRequest):
    """Make a real decision using multi-criteria analysis."""
    result = decision_engine.decide(req.question, req.options, req.criteria)
    return {
        "decision_id": result.decision_id,
        "best_option": result.best_option,
        "ranking": result.ranking,
        "risk_level": result.risk_level,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }


# ── Reasoning API ─────────────────────────────────────────────────────────

@app.post("/api/reasoning/bayesian")
async def bayesian(req: BayesianRequest):
    """Perform Bayesian probability updating."""
    hyp = reasoning_engine.bayesian_update(req.hypothesis, req.prior, req.evidence, req.likelihood)
    return {
        "hypothesis_id": hyp.hypothesis_id,
        "prior": hyp.prior_probability,
        "posterior": hyp.posterior_probability,
        "likelihood": hyp.likelihood,
    }


# ── Memory API ────────────────────────────────────────────────────────────

@app.post("/api/memory/store")
async def memory_store(req: MemoryStoreRequest):
    """Store a memory."""
    mem = memory_engine.store(req.content, req.agent_origin, req.tags, req.importance)
    return {"memory_id": mem.memory_id, "status": "stored"}


@app.post("/api/memory/search")
async def memory_search(req: MemorySearchRequest):
    """Search memories."""
    results = memory_engine.search(req.query, limit=req.limit, tags=req.tags)
    return {
        "results": [
            {"memory_id": r.memory_id, "content": r.content, "score": r.score, "snippet": r.snippet}
            for r in results
        ],
        "total": len(results),
    }


# ── Trading API ──────────────────────────────────────────────────────────

@app.post("/api/trading/signals")
async def trading_signals(req: TradingBacktestRequest):
    """Signals from the same strategies used by Stratex backtests."""
    from dataclasses import asdict
    bars = [_stratex.PriceBar(i, p, p, p, p) for i, p in enumerate(req.prices)]
    try:
        return {"symbol": req.symbol, "strategy": req.strategy,
                "signals": [asdict(s) for s in trading_engine.generate_signals(req.symbol, bars, req.strategy)]}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/api/trading/backtest")
async def trading_backtest(req: TradingBacktestRequest):
    """Run a backtest."""
    bars = [
        _stratex.PriceBar(timestamp=i, open=p, high=p+0.5, low=p-0.5, close=p, volume=10000)
        for i, p in enumerate(req.prices)
    ]
    try:
        result = trading_engine.backtest(req.symbol, bars, req.strategy, req.initial_capital,
                                        req.position_size_pct, req.fee_pct, req.slippage_pct,
                                        req.stop_loss_pct, req.take_profit_pct)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {
        "symbol": result.symbol,
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "win_rate_pct": result.win_rate_pct,
        "total_trades": result.total_trades,
        "final_equity": result.final_equity,
    }


# ── Code API ──────────────────────────────────────────────────────────────

@app.post("/api/code/analyze")
async def code_analyze(req: CodeAnalyzeRequest):
    """Analyze code."""
    analysis = code_engine.analyze(req.code, req.language)
    return {
        "lines_of_code": analysis.lines_of_code,
        "classes": analysis.number_of_classes,
        "methods": analysis.number_of_methods,
        "complexity": analysis.cyclomatic_complexity,
        "maintainability": analysis.maintainability_index,
        "issues": analysis.issues,
        "suggestions": analysis.suggestions,
    }


# ── Security API ──────────────────────────────────────────────────────────

@app.post("/api/security/scan")
async def security_scan(req: SecurityScanRequest):
    """Scan code and logs for threats."""
    vulns = security_engine.scan_code(req.code, "input")
    threats = security_engine.detect_threats(req.logs, "api")
    posture = security_engine.assess_posture()
    return {
        "vulnerabilities": len(vulns),
        "threats": len(threats),
        "posture_score": posture.score,
        "posture_level": posture.level,
    }


# ── Threat Intel API ──────────────────────────────────────────────────────

@app.post("/api/threat/correlate")
async def threat_correlate(req: ThreatCorrelateRequest):
    """Correlate threat indicators."""
    ids = []
    for ind in req.indicators:
        result = threat_engine.add_indicator(
            ind["value"], ind["type"], ind.get("confidence", 0.5), ind.get("tags", [])
        )
        ids.append(result.indicator_id)
    correlations = threat_engine.correlate_indicators(ids)
    return {"correlations": len(correlations), "indicators": len(ids)}


# ── Forecast API ─────────────────────────────────────────────────────────

@app.post("/api/forecast/ensemble")
async def forecast_ensemble(req: ForecastRequest):
    """Generate ensemble forecast."""
    forecast = forecast_engine.ensemble_forecast(req.symbol, req.series)
    return {
        "prediction": forecast.prediction,
        "lower_bound": forecast.lower_bound,
        "upper_bound": forecast.upper_bound,
        "confidence": forecast.confidence,
        "model": forecast.model_name,
    }


# ── Content API ──────────────────────────────────────────────────────────

@app.post("/api/content/predict")
async def content_predict(req: ContentPredictRequest):
    """Predict content performance."""
    prediction = content_engine.predict_performance(req.title, req.description, req.tags)
    return prediction


# ── Workflow API ──────────────────────────────────────────────────────────

@app.post("/api/workflow/trading")
async def workflow_trading(req: WorkflowRequest):
    """Run a trading workflow."""
    if not req.prices:
        raise HTTPException(status_code=400, detail="prices required")
    result = cross_engine.run_trading_workflow(req.symbol or "TEST", req.prices, strategy=req.strategy)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "steps": len(result.steps),
        "final_output": result.final_output,
        "total_time_ms": result.total_time_ms,
    }


@app.post("/api/workflow/security")
async def workflow_security(req: WorkflowRequest):
    """Run a security workflow."""
    result = cross_engine.run_security_workflow(req.code or "", req.logs or "")
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "steps": len(result.steps),
        "final_output": result.final_output,
    }


@app.post("/api/workflow/code")
async def workflow_code(req: WorkflowRequest):
    """Run a code workflow."""
    result = cross_engine.run_code_workflow(req.topic or "function")
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "steps": len(result.steps),
        "final_output": result.final_output,
    }


@app.post("/api/workflow/content")
async def workflow_content(req: WorkflowRequest):
    """Run a content workflow."""
    result = cross_engine.run_content_workflow(req.topic or "Test", req.topic or "Test")
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "steps": len(result.steps),
        "final_output": result.final_output,
    }


# ── Deep API ────────────────────────────────────────────────────────────

class DeepRecommendRequest(BaseModel):
    user_id: str
    item_features: dict[str, dict[str, float]] = {}
    item_interactions: dict[str, list[str]] = {}


class DeepPredictRequest(BaseModel):
    model_id: str
    features: dict[str, float]
    training_data: list[dict] = []
    targets: list[float] = []


class DeepForesightRequest(BaseModel):
    topic: str
    factors: list[str]


class DeepSentimentRequest(BaseModel):
    symbol: str
    text: str


class DeepOrderFlowRequest(BaseModel):
    symbol: str
    trades: list[dict]


class DeepPatternRequest(BaseModel):
    symbol: str
    prices: list[float]


class DeepCodeScanRequest(BaseModel):
    code: str
    filename: str = "unknown"


class DeepDepsRequest(BaseModel):
    requirements: dict[str, str]


class DeepRefactorRequest(BaseModel):
    code: str
    filename: str = "unknown"


class DeepVulnMgmtRequest(BaseModel):
    cve_id: str
    severity: str
    name: str
    description: str
    score: float
    component: str


class DeepComplianceRequest(BaseModel):
    framework: str


class DeepIncidentRequest(BaseModel):
    incident_type: str


class DeepThreatForecastRequest(BaseModel):
    threat_type: str
    history: list[dict]


class DeepIntelQualityRequest(BaseModel):
    source_id: str
    indicators: list[dict]
    feedback: list[dict] = []


class DeepDisinfoRequest(BaseModel):
    text: str


class DeepEnsembleRequest(BaseModel):
    model_forecasts: dict[str, float]
    weights: dict[str, float]


class DeepForecastRequest(BaseModel):
    series: list[float]
    method: str = "auto"
    horizon: int = 10


class DeepStressRequest(BaseModel):
    baseline: float
    scenarios: list[dict] = []


class DeepAudienceRequest(BaseModel):
    viewers: list[dict]


class DeepGrowthRequest(BaseModel):
    channel_stats: dict


class DeepModerationRequest(BaseModel):
    content_id: str
    text: str


@app.post("/api/deep/recommend")
async def deep_recommend(req: DeepRecommendRequest):
    engine = _cortex_deep.RecommendationPersonalizer()
    for item, features in req.item_features.items():
        engine.add_item_features(item, features)
    for user, items in req.item_interactions.items():
        for item in items:
            engine.record_interaction(user, item)
    recs = engine.recommend_collaborative(req.user_id, top_k=5)
    return {"user_id": req.user_id, "recommendations": [r.item_id for r in recs],
            "scores": [r.score for r in recs]}


@app.post("/api/deep/predict")
async def deep_predict(req: DeepPredictRequest):
    engine = _cortex_deep.PredictiveAnalyticsEngine()
    if req.training_data and req.targets:
        engine.train_linear_regression(req.model_id, req.training_data, req.targets)
    prediction = engine.predict(req.model_id, req.features)
    return {"model_id": req.model_id, "prediction": prediction.prediction,
            "confidence": prediction.confidence, "method": prediction.method}


@app.post("/api/deep/foresight")
async def deep_foresight(req: DeepForesightRequest):
    scenarios = _cortex_deep.foresight.generate_scenarios(req.topic, req.factors)
    return {"topic": req.topic, "scenarios": [
        {"name": s.name, "probabilities": s.probabilities,
         "actions": s.preparation_actions} for s in scenarios
    ]}


@app.post("/api/deep/sentiment")
async def deep_sentiment(req: DeepSentimentRequest):
    result = _stratex_deep.sentiment_engine.analyze(req.symbol, req.text)
    return {"symbol": req.symbol, "score": result.sentiment_score,
            "sentiment": result.dominant_sentiment, "confidence": result.confidence,
            "top_words": result.top_words}


@app.post("/api/deep/orderflow")
async def deep_orderflow(req: DeepOrderFlowRequest):
    result = _stratex_deep.order_flow.analyze(req.symbol, req.trades)
    return {"symbol": req.symbol, "imbalance": result.imbalance,
            "signal": result.signal, "flow_ratio": result.flow_ratio}


@app.post("/api/deep/patterns")
async def deep_patterns(req: DeepPatternRequest):
    patterns = _stratex_deep.pattern_engine.detect_patterns(req.symbol, req.prices)
    return {"symbol": req.symbol, "patterns": [
        {"name": p.pattern, "confidence": p.confidence,
         "breakout": p.breakout_level, "target": p.target_price,
         "stop_loss": p.stop_loss} for p in patterns
    ]}


@app.post("/api/deep/security-scan")
async def deep_security_scan(req: DeepCodeScanRequest):
    findings = _forge_deep.security_scanner.scan(req.code, req.filename)
    return {"filename": req.filename, "findings": [
        {"category": f.category, "line": f.line, "severity": f.severity,
         "cwe": f.cwe_id, "description": f.description, "remediation": f.remediation}
        for f in findings
    ], "summary": _forge_deep.security_scanner.get_summary(findings)}


@app.post("/api/deep/deps")
async def deep_deps(req: DeepDepsRequest):
    result = _forge_deep.dependency_analyzer.analyze(req.requirements)
    return {"total": result.total_dependencies,
            "vulnerable": result.vulnerable_dependencies,
            "outdated": result.outdated_dependencies}


@app.post("/api/deep/refactor")
async def deep_refactor(req: DeepRefactorRequest):
    suggestions = _forge_deep.refactoring_engine.analyze(req.code, req.filename)
    return {"filename": req.filename, "suggestions": [
        {"issue": s.issue, "line": s.line, "suggestion": s.suggestion,
         "impact": s.impact, "pattern": s.pattern} for s in suggestions
    ], "count": len(suggestions)}


@app.post("/api/deep/vuln-mgmt")
async def deep_vuln_mgmt(req: DeepVulnMgmtRequest):
    engine = _sentinel_deep.VulnerabilityManagementSystem()
    engine.add_vulnerability(req.cve_id, req.severity, req.name,
                               req.description, req.score, req.component)
    summary = engine.get_vulnerability_summary()
    return {"summary": summary}


@app.post("/api/deep/compliance")
async def deep_compliance(req: DeepComplianceRequest):
    checks = _sentinel_deep.compliance_audit.audit(req.framework)
    score = _sentinel_deep.compliance_audit.compliance_score(checks)
    return {"framework": req.framework, "score": score, "checks": [
        {"name": c.description, "status": c.status,
         "details": c.evidence, "remediation": c.remediation} for c in checks
    ]}


@app.post("/api/deep/incidents")
async def deep_incidents(req: DeepIncidentRequest):
    steps = _sentinel_deep.incident_playbook.execute_playbook(req.incident_type)
    return {"incident_type": req.incident_type, "steps": [
        {"name": s.name, "status": s.status, "details": s.description} for s in steps
    ]}


@app.post("/api/deep/threat-forecast")
async def deep_threat_forecast(req: DeepThreatForecastRequest):
    result = _intelx_deep.threat_forecast.forecast(req.threat_type, req.history)
    return {"threat_type": req.threat_type, "probability": result.probability,
            "trend": result.trend, "confidence": result.confidence,
            "indicators": result.indicators}


@app.post("/api/deep/intel-quality")
async def deep_intel_quality(req: DeepIntelQualityRequest):
    result = _intelx_deep.quality_evaluator.evaluate(req.source_id, req.indicators, req.feedback)
    return {"source_id": req.source_id, "overall": result.overall,
            "grade": result.grade, "scores": {
                "completeness": result.completeness,
                "accuracy": result.accuracy,
                "timeliness": result.timeliness,
                "relevance": result.relevance,
            }}


@app.post("/api/deep/disinfo")
async def deep_disinfo(req: DeepDisinfoRequest):
    result = _intelx_deep.disinfo_detector.detect(req.text)
    return {"is_disinformation": result.is_disinformation,
            "score": result.fact_check_score,
            "indicators": result.indicators}


@app.post("/api/deep/ensemble")
async def deep_ensemble(req: DeepEnsembleRequest):
    ensemble, confidence = _futuris_deep.ensemble_selector.create_ensemble_forecast(
        req.model_forecasts, req.weights)
    return {"ensemble_forecast": ensemble, "confidence": confidence}


@app.post("/api/deep/forecast")
async def deep_forecast(req: DeepForecastRequest):
    result = _futuris_deep.forecasting_engine.forecast(req.series, req.method, req.horizon)
    return {"method": result.method, "forecast": result.forecast_values,
            "mape": result.mape, "intervals": result.confidence_intervals}


@app.post("/api/deep/stress")
async def deep_stress(req: DeepStressRequest):
    if req.scenarios:
        results = _futuris_deep.stress_tester.run_stress_test(req.baseline, req.scenarios)
    else:
        results = _futuris_deep.stress_tester.standard_scenarios(req.baseline)
    return {"baseline": req.baseline, "scenarios": [
        {"name": s.name, "description": s.description,
         "shock_pct": s.shock_pct, "stressed": s.stressed, "impact": s.impact}
        for s in results
    ]}


@app.post("/api/deep/audience")
async def deep_audience(req: DeepAudienceRequest):
    segments = _vyralx_deep.audience_intel.analyze_audience(req.viewers)
    summary = _vyralx_deep.audience_intel.get_audience_summary(segments)
    return {"summary": summary, "segments": [
        {"name": s.name, "size": s.size, "interests": s.interests,
         "engagement": s.engagement_rate} for s in segments
    ]}


@app.post("/api/deep/growth")
async def deep_growth(req: DeepGrowthRequest):
    strategies = _vyralx_deep.growth_strategy.generate_strategies(req.channel_stats)
    recommended = _vyralx_deep.growth_strategy.get_recommended_strategy(req.channel_stats, strategies)
    return {"strategies": [
        {"name": s.name, "growth_pct": s.expected_growth_pct,
         "effort": s.effort, "timeline": s.timeline_days} for s in strategies
    ], "recommended": recommended.name}


@app.post("/api/deep/moderation")
async def deep_moderation(req: DeepModerationRequest):
    result = _vyralx_deep.moderation_engine.moderate(req.content_id, req.text)
    return {"action": result.action, "reason": result.reason,
            "category": result.category, "confidence": result.confidence}


# ── Deep Workflow Endpoints ──────────────────────────────────────────────

_orchestrator = load_engine("FRIDAY/apps/core/src/friday_core/universe_orchestrator.py", "api_orchestrator")
_universe_orch = _orchestrator.universe_orchestrator


class DeepSecurityWorkflowRequest(BaseModel):
    code: str
    logs: list[str] = []


class DeepTradingWorkflowRequest(BaseModel):
    symbol: str
    prices: list[float]
    trades: list[dict] = []


class DeepIntelWorkflowRequest(BaseModel):
    indicators: list[dict]


class DeepContentWorkflowRequest(BaseModel):
    topic: str
    content_text: str
    viewers: list[dict] = []


@app.post("/api/workflow/deep/security")
async def deep_security_workflow(req: DeepSecurityWorkflowRequest):
    result = _universe_orch.run_deep_security(req.code, req.logs)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "complexity": result.complexity,
        "steps": len(result.steps),
        "final_output": result.final_output,
        "total_duration_ms": result.total_duration_ms,
    }


@app.post("/api/workflow/deep/trading")
async def deep_trading_workflow(req: DeepTradingWorkflowRequest):
    result = _universe_orch.run_deep_trading(req.symbol, req.prices, req.trades)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "complexity": result.complexity,
        "steps": len(result.steps),
        "final_output": result.final_output,
        "total_duration_ms": result.total_duration_ms,
    }


@app.post("/api/workflow/deep/intel")
async def deep_intel_workflow(req: DeepIntelWorkflowRequest):
    result = _universe_orch.run_deep_intel(req.indicators)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "complexity": result.complexity,
        "steps": len(result.steps),
        "final_output": result.final_output,
        "total_duration_ms": result.total_duration_ms,
    }


@app.post("/api/workflow/deep/content")
async def deep_content_workflow(req: DeepContentWorkflowRequest):
    result = _universe_orch.run_deep_content(req.topic, req.content_text, req.viewers)
    return {
        "workflow_id": result.workflow_id,
        "status": result.status,
        "complexity": result.complexity,
        "steps": len(result.steps),
        "final_output": result.final_output,
        "total_duration_ms": result.total_duration_ms,
    }


@app.get("/api/dashboard")
async def universe_dashboard():
    from friday_core.universe_dashboard import universe_dashboard as dash_instance
    return dash_instance.get_dashboard_data()


@app.get("/api/dashboard/benchmarks")
async def dashboard_benchmarks():
    from friday_core.universe_dashboard import universe_dashboard as dash_instance
    return dash_instance.get_benchmarks()


@app.get("/api/dashboard/alerts")
async def dashboard_alerts():
    from friday_core.universe_dashboard import universe_dashboard as dash_instance
    return {"alerts": dash_instance._alert_manager.get_alerts()}


@app.get("/api/dashboard/agents")
async def dashboard_agents():
    from friday_core.universe_dashboard import universe_dashboard as dash_instance
    return dash_instance._monitor.get_status()


# ── Status API ───────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    """Get universe status."""
    return cross_engine.get_universe_status()


@app.get("/", include_in_schema=False)
async def assistant_home():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/v2/assistant")


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "engines": 10, "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
