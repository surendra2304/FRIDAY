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

@app.post("/api/trading/backtest")
async def trading_backtest(req: TradingBacktestRequest):
    """Run a backtest."""
    from real_trading_engine import PriceBar
    bars = [
        PriceBar(timestamp=i, open=p, high=p+0.5, low=p-0.5, close=p, volume=10000)
        for i, p in enumerate(req.prices)
    ]
    result = trading_engine.backtest(req.symbol, bars, req.strategy, req.initial_capital)
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
    result = cross_engine.run_trading_workflow(req.symbol or "TEST", req.prices)
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


# ── Status API ───────────────────────────────────────────────────────────

@app.get("/api/status")
async def status():
    """Get universe status."""
    return cross_engine.get_universe_status()


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "engines": 10, "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
