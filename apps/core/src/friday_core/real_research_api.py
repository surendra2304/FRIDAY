"""Shared, bounded HTTP routes connecting source-derived behavior to FRIDAY agents."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from threading import RLock
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field


class MarketObservation(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    price: float = Field(gt=0, allow_inf_nan=False)
    previous_close: float = Field(gt=0, allow_inf_nan=False)
    closes: list[float | None] = Field(max_length=10000)


class ResearchDocument(BaseModel):
    engine_url: str = Field(default="", max_length=4096)
    url: str = Field(max_length=4096)
    title: str = Field(max_length=1000)
    text: str = Field(default="", max_length=100000)


class ResearchRequest(BaseModel):
    documents: list[ResearchDocument] = Field(max_length=100)
    per_host_limit: int = Field(default=3, ge=1, le=100)
    allow_clearweb: bool = False


class AssistantRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    market: MarketObservation | None = None
    documents: list[ResearchDocument] | None = Field(default=None, max_length=100)
    ohlcv_bars: list[dict[str, float]] | None = Field(default=None, max_length=5000)
    business_data: dict[str, Any] | None = None


class InvestigationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    preset: str = Field(min_length=1, max_length=40)
    user_chose_preset: bool = False
    custom_instructions: str = Field(default="", max_length=5000)
    use_cloud_model: bool = False
    max_results: int = Field(default=30, ge=1, le=100)
    max_scrape: int = Field(default=10, ge=1, le=100)
    threads: int = Field(default=4, ge=1, le=16)
    content_chars: int = Field(default=12000, ge=500, le=100000)
    per_host_limit: int = Field(default=3, ge=1, le=100)
    allow_clearweb: bool = False


class FollowupRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_cloud_model: bool = False


class RobinFilterRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_scrape: int = Field(default=10, ge=1, le=100)
    use_cloud_model: bool | None = None


class RobinScrapeRequest(BaseModel):
    result_ids: list[str] | None = Field(default=None, max_length=100)
    threads: int = Field(default=4, ge=1, le=16)
    content_chars: int = Field(default=12000, ge=500, le=100000)


class WatchlistRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, max_length=50)


class ActionApproval(BaseModel):
    action_id: str = Field(min_length=32, max_length=32)
    approved: bool = False


class VoiceRequest(BaseModel):
    wav_base64: str = Field(max_length=14000000)
    speak: bool = True
    allow_cloud_transcription: bool = False
    allow_cloud_synthesis: bool = False


class CoachReviewRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    bars: list[dict[str, float]] = Field(min_length=5, max_length=5000)
    lookback: int = Field(default=50, ge=5, le=500)
    volume_threshold: float = Field(default=1.5, gt=0, allow_inf_nan=False)
    latest_bar_complete: bool = False


class PositionPlanRequest(BaseModel):
    side: str
    entry: float = Field(gt=0, allow_inf_nan=False)
    stop: float = Field(gt=0, allow_inf_nan=False)
    target: float = Field(gt=0, allow_inf_nan=False)
    account_equity: float = Field(gt=0, allow_inf_nan=False)
    risk_percent: float = Field(default=1.0, gt=0, le=100, allow_inf_nan=False)
    max_notional_multiple: float = Field(default=1.0, gt=0, le=100, allow_inf_nan=False)
    lot_size: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    fee_percent: float = Field(default=0.0, ge=0, le=10, allow_inf_nan=False)
    slippage_percent: float = Field(default=0.0, ge=0, le=10, allow_inf_nan=False)


class ExpectancyRequest(BaseModel):
    results_r: list[float] = Field(min_length=1, max_length=100000)


class JournalTradeRequest(BaseModel):
    trade_id: str = Field(min_length=1, max_length=100)
    symbol: str = Field(min_length=1, max_length=40)
    side: str
    entry: float = Field(gt=0, allow_inf_nan=False)
    stop: float = Field(gt=0, allow_inf_nan=False)
    quantity: float = Field(gt=0, allow_inf_nan=False)
    target: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    opened_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    exit_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    closed_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    emotion: str = Field(default="", max_length=300)
    followed_plan: bool | None = None
    notes: str = Field(default="", max_length=4000)
    fees: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class CorrelationRequest(BaseModel):
    series: dict[str, list[float]]
    threshold: float = Field(default=0.8, ge=-1, le=1, allow_inf_nan=False)


class BusinessRunRequest(BaseModel):
    data: dict[str, Any]


class IdeaImportRequest(BaseModel):
    text: str = Field(min_length=100, max_length=2000000)
    source_file: str = Field(default="Drive business ideas playbook", max_length=300)


class IdeaSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)


class IdeaScoreRequest(BaseModel):
    idea: dict[str, Any]


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    workflow: str
    spec: dict[str, Any]


class RoutineRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=80)
    weekdays: list[int] = Field(min_length=1, max_length=7)
    local_time: str = Field(min_length=5, max_length=8)
    timezone: str = Field(min_length=1, max_length=80)
    max_snapshot_age_hours: float = Field(default=24.0, ge=0.25, le=720, allow_inf_nan=False)


class RoutineStateRequest(BaseModel):
    enabled: bool


class RoutineRunRequest(BaseModel):
    data: dict[str, Any] | None = None


class BusinessSnapshotRequest(BaseModel):
    payload: dict[str, Any] | list[Any]
    observed_at: str | None = Field(default=None, max_length=80)
    source_link: str = Field(default="", max_length=1000)


def create_research_router(engine: Any) -> APIRouter:
    router = APIRouter(tags=["FRIDAY agent integrations"])
    lock = RLock()

    def require_operator(token: str | None) -> None:
        import hmac
        expected = os.environ.get("FRIDAY_LOCAL_ACTION_TOKEN", "")
        if not expected or not token or not hmac.compare_digest(token, expected):
            raise HTTPException(403, "Operator token required; configure FRIDAY_LOCAL_ACTION_TOKEN")

    def bounded_payload(data: dict[str, Any], maximum: int = 1000000) -> None:
        if len(json.dumps(data, ensure_ascii=False, allow_nan=False)) > maximum:
            raise HTTPException(413, "Request data exceeds the configured size limit")

    @router.post("/api/trading/momentum")
    def momentum(request: MarketObservation):
        try:
            with lock:
                return asdict(engine._trading.analyze_momentum(**request.model_dump()))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/trading/watchlist")
    def watchlist(request: WatchlistRequest):
        try:
            with lock:
                return engine._trading.live_market_report(request.symbols)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/threat/research")
    def research(request: ResearchRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        bounded_payload({"documents":[d.model_dump() for d in request.documents]},10_000_000)
        with lock:
            return engine.research_threats([d.model_dump() for d in request.documents],
                                           request.per_host_limit, request.allow_clearweb)

    @router.post("/api/assistant/respond")
    def assistant(request: AssistantRequest,
                  x_friday_operator: str | None = Header(default=None)):
        if request.documents is not None or request.business_data is not None:
            require_operator(x_friday_operator)
            bounded_payload({"documents":[d.model_dump() for d in request.documents] if request.documents is not None else None,
                             "business_data":request.business_data},10_000_000)
        try:
            with lock:
                return engine.assistant_reply(request.query,
                    market=request.market.model_dump() if request.market else None,
                    documents=[d.model_dump() for d in request.documents] if request.documents is not None else None,
                    ohlcv_bars=request.ohlcv_bars, business_data=request.business_data)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/assistant/vitals")
    def vitals(x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        return engine.local_action_engine().vitals()

    @router.post("/api/assistant/actions/approve")
    def approve(request: ActionApproval, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            with lock:
                return engine.local_action_engine().execute(request.action_id, request.approved)
        except KeyError as error:
            raise HTTPException(404, "Action missing or already consumed") from error

    @router.post("/api/assistant/voice")
    def voice(request: VoiceRequest):
        import base64
        import binascii
        if not request.allow_cloud_transcription:
            raise HTTPException(403, "Explicit consent required for cloud audio transcription")
        try:
            audio = base64.b64decode(request.wav_base64, validate=True)
            with lock:
                turn = engine.voice_engine().turn(audio, request.speak, request.allow_cloud_synthesis)
            return {"transcript": turn.transcript, "response": turn.response,
                    "speech_status": turn.speech_status, "wav_base64": base64.b64encode(turn.audio).decode()}
        except (ValueError, binascii.Error) as error:
            raise HTTPException(422, str(error)) from error
        except (RuntimeError, OSError) as error:
            raise HTTPException(503, "Speech provider unavailable; use the text endpoint") from error

    @router.get("/api/trading/coach/curriculum")
    def curriculum():
        return engine.trading_coach().lesson_catalog()

    @router.post("/api/trading/coach/review")
    def coach_review(request: CoachReviewRequest):
        try:
            bars = [engine._trading.price_bar_from_mapping(item) for item in request.bars]
            return asdict(engine.trading_coach().review_market(request.symbol, bars,
                request.lookback, request.volume_threshold, request.latest_bar_complete))
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/trading/coach/position-plan")
    def position_plan(request: PositionPlanRequest):
        try:
            return asdict(engine.trading_coach().size_position(**request.model_dump()))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/trading/coach/expectancy")
    def expectancy(request: ExpectancyRequest):
        try:
            return asdict(engine.trading_coach().expectancy(request.results_r))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/trading/coach/correlation")
    def correlation(request: CorrelationRequest):
        try:
            return engine.trading_coach().correlations(request.series, request.threshold)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/trading/coach/journal")
    def journal_trade(request: JournalTradeRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.trading_coach().record_trade(**request.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.get("/api/trading/coach/journal/review")
    def journal_review(x_friday_operator: str | None = Header(default=None), limit: int = 500):
        require_operator(x_friday_operator)
        try:
            return asdict(engine.trading_coach().review_journal(limit))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error

    @router.get("/api/business/catalog")
    def business_catalog():
        from friday_core.real_business_ops_engine import IDEA_SOURCE, GROK_WORKFLOWS
        return {"idea_source": IDEA_SOURCE, "workflows": GROK_WORKFLOWS,
                "safety": "All workflows are read-only over caller-supplied snapshots; no routine sends or edits records."}

    @router.post("/api/business/ideas/import")
    def import_ideas(request: IdeaImportRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.business_ops_engine().import_ideas(request.text, request.source_file)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/ideas/search")
    def search_ideas(request: IdeaSearchRequest):
        try:
            return engine.business_ops_engine().recommend_ideas(request.query, request.limit)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/ideas/score")
    def score_idea(request: IdeaScoreRequest):
        try:
            return engine.business_ops_engine().score_idea(request.idea)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/workflows/{workflow}/run")
    def run_business_workflow(workflow: str, request: BusinessRunRequest,
                              x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        bounded_payload(request.data)
        try:
            return asdict(engine.business_ops_engine().run(workflow, request.data))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/snapshots/{source_id}")
    def ingest_business_snapshot(source_id: str, request: BusinessSnapshotRequest,
                                 x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        bounded_payload(request.payload if isinstance(request.payload, dict) else {"items": request.payload})
        try:
            return engine.business_ops_engine().ingest_snapshot(source_id, request.payload,
                request.observed_at, request.source_link)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/skills")
    def create_skill(request: SkillRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.business_ops_engine().create_skill(request.name, request.workflow, request.spec)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/business/skills")
    def list_skills(x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        return engine.business_ops_engine().list_skills()

    @router.post("/api/business/routines")
    def create_routine(request: RoutineRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.business_ops_engine().create_routine(request.skill_id, request.weekdays,
                request.local_time, request.timezone, request.max_snapshot_age_hours)
        except KeyError as error:
            raise HTTPException(404, "Skill not found") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/business/routines")
    def list_routines(x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        return engine.business_ops_engine().list_routines()

    @router.patch("/api/business/routines/{routine_id}")
    def routine_state(routine_id: str, request: RoutineStateRequest,
                      x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.business_ops_engine().set_routine_enabled(routine_id, request.enabled)
        except KeyError as error:
            raise HTTPException(404, "Routine not found") from error

    @router.get("/api/business/routines/{routine_id}/next-run")
    def routine_next_run(routine_id: str, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.business_ops_engine().next_run(routine_id)
        except KeyError as error:
            raise HTTPException(404, "Routine not found") from error

    @router.post("/api/business/routines/{routine_id}/run")
    def run_routine(routine_id: str, request: RoutineRunRequest,
                    x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        if request.data is not None:
            bounded_payload(request.data)
        try:
            return engine.business_ops_engine().run_routine(routine_id, request.data)
        except KeyError as error:
            raise HTTPException(404, "Routine not found") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/business/routines/due")
    def run_due_routines(x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        return engine.business_ops_engine().run_due_all()

    @router.post("/api/threat/investigations")
    def investigate(request: InvestigationRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            with lock:
                return engine.investigation_engine().run(**request.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/threat/robin/search")
    def robin_search(request: InvestigationRequest, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        if not request.user_chose_preset:
            raise HTTPException(422, "Select a research domain before searching")
        try:
            investigator = engine.investigation_engine()
            query = investigator.refine_query(request.query, request.use_cloud_model)
            with lock:
                result = investigator.search(query, request.preset, True, request.max_results,
                    request.per_host_limit, request.threads, request.allow_clearweb, request.use_cloud_model)
            return {**result, "refined_query": query}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/threat/robin/{search_id}/filter")
    def robin_filter(search_id: str, request: RobinFilterRequest,
                     x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            with lock:
                return engine.investigation_engine().filter(search_id, request.query,
                    request.max_scrape, request.use_cloud_model)
        except KeyError as error:
            raise HTTPException(404, "Search session not found or expired") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/threat/robin/{search_id}/scrape")
    def robin_scrape(search_id: str, request: RobinScrapeRequest,
                     x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            with lock:
                return engine.investigation_engine().scrape(search_id, request.result_ids,
                                                           request.threads, request.content_chars)
        except KeyError as error:
            raise HTTPException(404, "Search session not found or expired") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/threat/robin/health")
    def robin_health():
        return engine.investigation_engine().health()

    @router.get("/api/threat/robin/models")
    def robin_models():
        return engine.investigation_engine().list_models()

    @router.get("/api/threat/investigations")
    def investigations(query: str = "", limit: int = 50,
                       x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.investigation_engine().store.list(query, limit)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/threat/investigations/{case_id}")
    def investigation(case_id: str, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.investigation_engine().store.get(case_id)
        except KeyError as error:
            raise HTTPException(404, "Investigation not found") from error

    @router.post("/api/threat/investigations/{case_id}/followup")
    def followup(case_id: str, request: FollowupRequest,
                 x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        try:
            return engine.investigation_engine().followup(case_id, request.question, request.use_cloud_model)
        except KeyError as error:
            raise HTTPException(404, "Investigation not found") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/threat/investigations/{case_id}/export")
    def export(case_id: str, format: str = "markdown",
               x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        from fastapi.responses import Response
        try:
            body = engine.investigation_engine().export(case_id, format)
            return Response(body, media_type="application/json" if format == "json" else "text/markdown")
        except KeyError as error:
            raise HTTPException(404, "Investigation not found") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.delete("/api/threat/investigations/{case_id}")
    def delete_investigation(case_id: str, x_friday_operator: str | None = Header(default=None)):
        require_operator(x_friday_operator)
        if not engine.investigation_engine().store.delete(case_id):
            raise HTTPException(404, "Investigation not found")
        return {"deleted": True}

    if os.environ.get("FRIDAY_ENABLE_ROUTINES", "").strip() == "1":
        poll_seconds = float(os.environ.get("FRIDAY_ROUTINE_POLL_SECONDS", "15"))
        def start_business_scheduler():
            engine.business_ops_engine().start_scheduler(poll_seconds)
        def stop_business_scheduler():
            if hasattr(engine, "_business_ops"):
                engine._business_ops.stop_scheduler()
        router.add_event_handler("startup", start_business_scheduler)
        router.add_event_handler("shutdown", stop_business_scheduler)

    # Keep the established APIs stable while exposing the new workplace contract.
    from .real_capability_api import create_capability_router
    router.include_router(create_capability_router(engine), prefix="/v2")
    return router
