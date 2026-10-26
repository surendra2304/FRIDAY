"""Shared API routes wiring Jarvis and Robin capabilities into actual engines."""
from __future__ import annotations

from dataclasses import asdict
from threading import RLock
from typing import Any

from fastapi import APIRouter, HTTPException
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


class AssistantRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    market: MarketObservation | None = None
    documents: list[ResearchDocument] | None = Field(default=None, max_length=100)


def create_research_router(engine: Any) -> APIRouter:
    router = APIRouter(tags=["Agent research and assistant"])
    lock = RLock()

    @router.post("/api/trading/momentum")
    def momentum(request: MarketObservation):
        try:
            with lock:
                return asdict(engine._trading.analyze_momentum(**request.model_dump()))
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/threat/research")
    def research(request: ResearchRequest):
        with lock:
            return engine.research_threats([d.model_dump() for d in request.documents], request.per_host_limit)

    @router.post("/api/assistant/respond")
    def assistant(request: AssistantRequest):
        try:
            with lock:
                return engine.assistant_reply(request.query,
                    market=request.market.model_dump() if request.market else None,
                    documents=[d.model_dump() for d in request.documents] if request.documents is not None else None)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    return router
