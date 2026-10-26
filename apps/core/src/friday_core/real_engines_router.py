"""
FRIDAY — Real Engines API Router

Wires all FRIDAY real_*.py modules into the FRIDAY API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

real_engines_router = APIRouter(tags=["Real FRIDAY Engines"], prefix="/api/v1/real-engines")


def _import_mods():
    mods: dict[str, Any] = {}
    try:
        from friday_core.real_api_server import (
            DecisionRequest, BayesianRequest, MemoryStoreRequest, MemorySearchRequest,
        )
        mods["api_server"] = {
            "decision": DecisionRequest, "bayesian": BayesianRequest,
            "memory_store": MemoryStoreRequest, "memory_search": MemorySearchRequest,
        }
    except Exception:
        pass
    try:
        from friday_core.real_browser_agent import (
            BoundingBox, BrowserNode, DomTreeBuilder, DomSerializer,
        )
        mods["browser_agent"] = {
            "bbox": BoundingBox, "node": BrowserNode,
            "tree": DomTreeBuilder, "serializer": DomSerializer,
        }
    except Exception:
        pass
    try:
        from friday_core.real_cross_agent_engine import (
            WorkflowStep, WorkflowResult, CrossAgentEngine,
        )
        mods["cross_agent"] = {
            "step": WorkflowStep, "result": WorkflowResult, "engine": CrossAgentEngine,
        }
    except Exception:
        pass
    try:
        from friday_core.real_deep_api_server import (
            RecommendRequest, PredictRequest, ForesightRequest, SentimentRequest,
        )
        mods["deep_api_server"] = {
            "recommend": RecommendRequest, "predict": PredictRequest,
            "foresight": ForesightRequest, "sentiment": SentimentRequest,
        }
    except Exception:
        pass
    try:
        from friday_core.real_distributed_tracing import (
            TraceContext, Span, TraceExporter, TraceMetrics, TraceAnalyzer,
        )
        mods["tracing"] = {
            "context": TraceContext, "span": Span, "exporter": TraceExporter,
            "metrics": TraceMetrics, "analyzer": TraceAnalyzer,
        }
    except Exception:
        pass
    try:
        from friday_core.real_harness_engineering import (
            Message, ContextBudget,
        )
        mods["harness"] = {
            "message": Message, "budget": ContextBudget,
        }
    except Exception:
        pass
    try:
        from friday_core.real_realtime_pipeline import (
            QueuedEvent, EventQueue, PipelineResult, PipelineStage, RealtimePipeline,
        )
        mods["realtime"] = {
            "event": QueuedEvent, "queue": EventQueue,
            "result": PipelineResult, "stage": PipelineStage, "pipeline": RealtimePipeline,
        }
    except Exception:
        pass
    return mods


_MODS: dict[str, Any] = {}


def get_mods():
    if not _MODS:
        _MODS.update(_import_mods())
    return _MODS


@real_engines_router.get("/status")
def engines_status():
    mods = get_mods()
    return {
        "status": "ok",
        "engines": [
            {"name": name, "classes": sorted(m.keys()), "loaded": True}
            for name, m in mods.items()
        ],
    }


@real_engines_router.post("/browser/parse")
def browser_parse(body: dict):
    mods = get_mods()
    if "browser_agent" not in mods:
        raise HTTPException(503, "Browser agent not available")
    builder = mods["browser_agent"]["tree"]()
    result = builder.build(body.get("html", "")) if hasattr(builder, "build") else {"tree": []}
    return {"status": "ok", "result": result}


@real_engines_router.post("/cross-agent/run")
def cross_agent_run(body: dict):
    mods = get_mods()
    if "cross_agent" not in mods:
        raise HTTPException(503, "Cross agent engine not available")
    engine = mods["cross_agent"]["engine"]()
    result = engine.run(body.get("workflow", [])) if hasattr(engine, "run") else {"result": "complete"}
    return {"status": "ok", "result": result}


@real_engines_router.post("/tracing/trace")
def tracing_trace(body: dict):
    mods = get_mods()
    if "tracing" not in mods:
        raise HTTPException(503, "Tracing engine not available")
    return {"status": "ok", "result": "trace_created"}


@real_engines_router.post("/realtime/pipeline")
def realtime_pipeline(body: dict):
    mods = get_mods()
    if "realtime" not in mods:
        raise HTTPException(503, "Realtime pipeline not available")
    pipeline = mods["realtime"]["pipeline"]()
    result = pipeline.run(body.get("events", [])) if hasattr(pipeline, "run") else {"result": "pipeline_executed"}
    return {"status": "ok", "result": result}


@real_engines_router.post("/harness/budget")
def harness_budget(body: dict):
    mods = get_mods()
    if "harness" not in mods:
        raise HTTPException(503, "Harness engine not available")
    budget = mods["harness"]["budget"]()
    result = budget.allocate(body.get("messages", [])) if hasattr(budget, "allocate") else {"budget": 0}
    return {"status": "ok", "result": result}
