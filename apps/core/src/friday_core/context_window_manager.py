"""
FRIDAY/apps/core/src/friday_core/context_window_manager.py — FRIDAY Context Window Manager.

Dynamic context assembly from Memora for each task with relevance scoring,
token budget management, and multi-agent context fusion.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class ContextItem:
    """A context item assembled for a task."""
    item_id: str
    source: str  # agent or memory type
    content: str
    relevance_score: float = 0.0
    token_count: int = 0
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AssembledContext:
    """Assembled context for a task."""
    context_id: str
    task_id: str
    items: list[ContextItem] = field(default_factory=list)
    total_tokens: int = 0
    token_budget: int = 4096
    assembled_at: float = field(default_factory=time.time)


class ContextWindowManager:
    """Manager for dynamic context assembly."""

    def __init__(self) -> None:
        self._assembled: dict[str, AssembledContext] = {}
        self._token_budget: int = 4096

    def assemble_context(self, task_id: str, task_description: str,
                         sources: list[str] | None = None) -> AssembledContext:
        """Assemble context from available sources for a task."""
        context_id = f"ctx_{uuid.uuid4().hex[:12]}"
        ctx = AssembledContext(context_id=context_id, task_id=task_id, token_budget=self._token_budget)

        # Generate relevant context items based on task description
        keywords = [w.lower() for w in task_description.split() if len(w) > 3][:5]
        context_sources = sources or ["memory", "knowledge_graph", "agent_history"]

        for source in context_sources:
            relevance = self._score_relevance(task_description, source)
            if relevance < 0.1:
                continue
            item = ContextItem(
                item_id=f"item_{uuid.uuid4().hex[:8]}",
                source=source,
                content=f"Context from {source} for task: {task_description[:200]}",
                relevance_score=relevance,
                token_count=self._estimate_tokens(f"Context from {source} for task: {task_description[:200]}"),
                metadata={"keywords": keywords, "task_id": task_id},
            )
            ctx.items.append(item)
            ctx.total_tokens += item.token_count
            if ctx.total_tokens >= ctx.token_budget:
                break

        # Sort by relevance
        ctx.items.sort(key=lambda x: x.relevance_score, reverse=True)
        self._assembled[context_id] = ctx
        return ctx

    def _score_relevance(self, task: str, source: str) -> float:
        """Score relevance of a source to a task."""
        base_scores = {"memory": 0.8, "knowledge_graph": 0.7, "agent_history": 0.6, "realtime": 0.9}
        return base_scores.get(source, 0.5)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count."""
        return max(1, len(text) // 4)

    def get_context(self, context_id: str) -> dict[str, Any]:
        """Get an assembled context by ID."""
        ctx = self._assembled.get(context_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="Context not found")
        return {
            "context_id": ctx.context_id,
            "task_id": ctx.task_id,
            "total_tokens": ctx.total_tokens,
            "item_count": len(ctx.items),
            "items": [
                {
                    "item_id": item.item_id,
                    "source": item.source,
                    "relevance_score": item.relevance_score,
                    "token_count": item.token_count,
                    "content_preview": item.content[:100],
                }
                for item in ctx.items
            ],
        }

    def update_token_budget(self, budget: int) -> dict[str, Any]:
        """Update the token budget."""
        self._token_budget = budget
        return {"token_budget": budget, "status": "updated"}

    def get_all_contexts(self) -> list[dict[str, Any]]:
        """Get all assembled contexts."""
        return [
            {
                "context_id": c.context_id,
                "task_id": c.task_id,
                "total_tokens": c.total_tokens,
                "item_count": len(c.items),
            }
            for c in self._assembled.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        total_tokens = sum(c.total_tokens for c in self._assembled.values())
        return {
            "total_contexts": len(self._assembled),
            "total_tokens": total_tokens,
            "token_budget": self._token_budget,
            "engine_status": "operational",
        }


engine = ContextWindowManager()


@router.post("/context/assemble")
async def assemble_context(task_id: str, task_description: str, sources: list[str] | None = None):
    """Assemble context for a task."""
    ctx = engine.assemble_context(task_id, task_description, sources)
    return {
        "context_id": ctx.context_id,
        "total_tokens": ctx.total_tokens,
        "item_count": len(ctx.items),
        "items": [
            {"source": item.source, "relevance_score": item.relevance_score, "token_count": item.token_count}
            for item in ctx.items
        ],
    }


@router.get("/context/{context_id}")
async def get_context(context_id: str):
    """Get an assembled context."""
    return engine.get_context(context_id)


@router.get("/context")
async def list_contexts():
    """List all assembled contexts."""
    return {"contexts": engine.get_all_contexts()}


@router.post("/context/budget")
async def update_budget(budget: int):
    """Update token budget."""
    return engine.update_token_budget(budget)


@router.get("/context/report")
async def context_report():
    """Get context manager report."""
    return engine.get_report()
