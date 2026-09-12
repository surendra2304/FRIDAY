"""Workspace awareness, struggle detection, and proactive suggestion engine."""

from friday.awareness.struggle_detector import (
    AppCategory,
    StruggleAnalysis,
    StruggleDetector,
    StruggleSignal,
)
from friday.awareness.suggestion_engine import (
    Suggestion,
    SuggestionEngine,
    SuggestionType,
    suggestion_engine,
)

__all__ = [
    "AppCategory",
    "StruggleAnalysis",
    "StruggleDetector",
    "StruggleSignal",
    "Suggestion",
    "SuggestionEngine",
    "SuggestionType",
    "suggestion_engine",
]
