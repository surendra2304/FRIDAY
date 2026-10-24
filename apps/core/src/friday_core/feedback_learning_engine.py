"""
FRIDAY/apps/core/src/friday_core/feedback_learning_engine.py — FRIDAY Feedback Learning Engine.

Learns from user feedback and past task outcomes to improve future
decisions with improvement suggestions and strategy refinement.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class FeedbackRecord:
    """A feedback record from a user or system."""
    feedback_id: str
    task_id: str
    source: str  # user, system, agent
    rating: float  # 1.0 - 5.0
    comment: str = ""
    improvement_suggestion: str = ""
    timestamp: float = field(default_factory=time.time)
    category: str = "general"  # performance, accuracy, speed, etc.


@dataclass
class LearningInsight:
    """An insight learned from feedback."""
    insight_id: str
    topic: str
    insight: str
    confidence: float = 0.5
    improvement: str = ""
    based_on_feedbacks: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class StrategyRefinement:
    """A refined strategy based on learning."""
    refinement_id: str
    strategy: str
    changes: str
    expected_improvement: float = 0.0
    confidence: float = 0.5
    created_at: float = field(default_factory=time.time)


class FeedbackLearningEngine:
    """Engine for learning from feedback and outcomes."""

    def __init__(self) -> None:
        self._feedbacks: dict[str, FeedbackRecord] = {}
        self._insights: dict[str, LearningInsight] = {}
        self._refinements: dict[str, StrategyRefinement] = {}
        self._strategy_weights: dict[str, float] = {}

    def submit_feedback(self, task_id: str, rating: float, comment: str = "",
                        source: str = "user", category: str = "general",
                        improvement_suggestion: str = "") -> str:
        """Submit feedback for a task."""
        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        feedback = FeedbackRecord(
            feedback_id=feedback_id,
            task_id=task_id,
            source=source,
            rating=rating,
            comment=comment,
            improvement_suggestion=improvement_suggestion,
            category=category,
        )
        self._feedbacks[feedback_id] = feedback
        # Generate insight from feedback
        self._generate_insight(feedback)
        return feedback_id

    def _generate_insight(self, feedback: FeedbackRecord) -> LearningInsight:
        """Generate a learning insight from feedback."""
        insight_id = f"ins_{uuid.uuid4().hex[:12]}"
        topic = feedback.category
        if feedback.rating < 3.0:
            insight_text = f"Low rating ({feedback.rating:.1f}) in {topic}: {feedback.comment[:100]}"
            improvement = feedback.improvement_suggestion or "Review approach and add more validation"
            confidence = 0.8
        elif feedback.rating > 4.0:
            insight_text = f"High rating ({feedback.rating:.1f}) in {topic}: approach is working well"
            improvement = "Continue current approach"
            confidence = 0.7
        else:
            insight_text = f"Medium rating ({feedback.rating:.1f}) in {topic}: mixed results"
            improvement = "Consider fine-tuning parameters"
            confidence = 0.5
        insight = LearningInsight(
            insight_id=insight_id,
            topic=topic,
            insight=insight_text,
            confidence=confidence,
            improvement=improvement,
            based_on_feedbacks=1,
        )
        self._insights[insight_id] = insight
        return insight

    def refine_strategy(self, strategy: str, change: str) -> StrategyRefinement:
        """Refine a strategy based on learned insights."""
        refinement_id = f"ref_{uuid.uuid4().hex[:12]}"
        refinement = StrategyRefinement(
            refinement_id=refinement_id,
            strategy=strategy,
            changes=change,
            expected_improvement=0.1,
            confidence=0.6,
        )
        self._refinements[refinement_id] = refinement
        self._strategy_weights[strategy] = self._strategy_weights.get(strategy, 0.5) + 0.1
        return refinement

    def get_insights(self, topic: str | None = None) -> list[dict[str, Any]]:
        """Get learning insights, optionally filtered by topic."""
        insights = list(self._insights.values())
        if topic:
            insights = [i for i in insights if i.topic == topic]
        return [
            {
                "insight_id": i.insight_id,
                "topic": i.topic,
                "insight": i.insight,
                "confidence": i.confidence,
                "improvement": i.improvement,
                "based_on_feedbacks": i.based_on_feedbacks,
            }
            for i in insights
        ]

    def get_strategy_recommendations(self) -> list[dict[str, Any]]:
        """Get strategy recommendations based on learned weights."""
        sorted_strategies = sorted(self._strategy_weights.items(), key=lambda x: x[1], reverse=True)
        return [
            {"strategy": s, "weight": w, "recommendation": f"Use '{s}' — learned weight: {w:.2f}"}
            for s, w in sorted_strategies
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        avg_rating = sum(f.rating for f in self._feedbacks.values()) / len(self._feedbacks) if self._feedbacks else 0
        return {
            "total_feedbacks": len(self._feedbacks),
            "average_rating": round(avg_rating, 2),
            "total_insights": len(self._insights),
            "total_refinements": len(self._refinements),
            "strategies_tracked": len(self._strategy_weights),
            "engine_status": "operational",
        }


engine = FeedbackLearningEngine()


@router.post("/learning/feedback")
async def submit_feedback(task_id: str, rating: float, comment: str = "",
                          source: str = "user", category: str = "general",
                          improvement_suggestion: str = ""):
    """Submit feedback for learning."""
    fb_id = engine.submit_feedback(task_id, rating, comment, source, category, improvement_suggestion)
    return {"feedback_id": fb_id, "status": "received"}


@router.get("/learning/insights")
async def get_insights(topic: str | None = None):
    """Get learning insights."""
    return {"insights": engine.get_insights(topic)}


@router.post("/learning/refine")
async def refine_strategy(strategy: str, change: str):
    """Refine a strategy based on learning."""
    ref = engine.refine_strategy(strategy, change)
    return {"refinement_id": ref.refinement_id, "strategy": ref.strategy, "status": "refined"}


@router.get("/learning/strategies")
async def get_strategies():
    """Get strategy recommendations."""
    return {"strategies": engine.get_strategy_recommendations()}


@router.get("/learning/report")
async def learning_report():
    """Get feedback learning report."""
    return engine.get_report()
