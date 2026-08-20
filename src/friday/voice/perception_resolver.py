# -*- coding: utf-8 -*-
"""Voice-to-Perception Reference Resolver for Phase 8.7.

Resolves spoken contextual references (e.g. "what is this", "what changed", "look at the error",
"open the thing we discussed") against ActiveTaskContext, TemporalEnvironmentTracker, and EpisodicMemory
to decide whether visual capture is necessary and formulate targeted query parameters.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple

from friday.core.logging import get_logger
from friday.memory.task_context import ActiveTaskContext
from friday.vision.active_perception import ActivePerceptionEngine, ObservationNecessity
from friday.vision.episodic_memory import EpisodicEnvironmentalMemoryManager
from friday.vision.screen_context import ScreenContext
from friday.vision.temporal import TemporalEnvironmentTracker

logger = get_logger("voice.perception_resolver")


class SpokenVisualIntentType(str, Enum):
    """Categorized types of visual / screen intents extracted from spoken voice utterances."""
    CURRENT_SCREEN = "CURRENT_SCREEN"            # "what is this", "what is on my screen", "read this"
    CHANGE_INQUIRY = "CHANGE_INQUIRY"            # "what changed", "is it done yet", "did it update"
    ERROR_INVESTIGATION = "ERROR_INVESTIGATION"  # "look at the error", "what failed", "why did it break"
    ELEMENT_ACTION = "ELEMENT_ACTION"            # "click the button", "open the tab", "press submit"
    HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"# "open the thing we discussed", "remember that window"
    NON_VISUAL = "NON_VISUAL"                    # "what time is it", "calculate 2 + 2", "tell me a joke"


# Regex heuristics for detecting spoken visual intent
VISUAL_PATTERNS = [
    (re.compile(r"\b(what is (this|that|on (my |the )?screen|visible)|look at (this|that|the screen|the window))\b", re.IGNORECASE), SpokenVisualIntentType.CURRENT_SCREEN),
    (re.compile(r"\b(what changed|did it (change|finish|update|complete)|any update)\b", re.IGNORECASE), SpokenVisualIntentType.CHANGE_INQUIRY),
    (re.compile(r"\b(look at (the )?error|what (is the )?error|why did it fail|what broke)\b", re.IGNORECASE), SpokenVisualIntentType.ERROR_INVESTIGATION),
    (re.compile(r"\b(click (the|that)|press (the|that)|open (the|that) (tab|button|window|menu))\b", re.IGNORECASE), SpokenVisualIntentType.ELEMENT_ACTION),
    (re.compile(r"\b(the thing (we|you) (were )?(talking about|discussed|mentioned))\b", re.IGNORECASE), SpokenVisualIntentType.HISTORICAL_REFERENCE),
]


@dataclass
class VoicePerceptionResolution:
    """Result of analyzing a spoken voice utterance for visual perception relevance."""
    intent_type: SpokenVisualIntentType
    requires_perception: bool
    targeted_query: Optional[str] = None
    target_element_label: Optional[str] = None
    resolved_context_summary: Optional[str] = None
    confidence: float = 0.9

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "requires_perception": self.requires_perception,
            "targeted_query": self.targeted_query,
            "target_element_label": self.target_element_label,
            "resolved_context_summary": self.resolved_context_summary,
            "confidence": self.confidence,
        }


class VoicePerceptionResolver:
    """Interprets spoken voice requests and fuses them with active vision, temporal, and episodic context."""

    def __init__(
        self,
        active_perception: Optional[ActivePerceptionEngine] = None,
        temporal_tracker: Optional[TemporalEnvironmentTracker] = None,
        episodic_memory: Optional[EpisodicEnvironmentalMemoryManager] = None,
    ) -> None:
        self.active_perception = active_perception or ActivePerceptionEngine()
        self.temporal_tracker = temporal_tracker
        self.episodic_memory = episodic_memory

    def classify_spoken_utterance(self, utterance: str) -> SpokenVisualIntentType:
        """Classify whether a spoken voice utterance involves visual or environmental context."""
        if not utterance or not utterance.strip():
            return SpokenVisualIntentType.NON_VISUAL

        text = utterance.strip()
        for pattern, intent_type in VISUAL_PATTERNS:
            if pattern.search(text):
                return intent_type

        return SpokenVisualIntentType.NON_VISUAL

    def resolve_voice_request(
        self,
        utterance: str,
        current_screen_context: Optional[ScreenContext] = None,
        task_context: Optional[ActiveTaskContext] = None,
    ) -> VoicePerceptionResolution:
        """Analyze voice utterance and determine if screen observation or reference resolution is needed."""
        intent = self.classify_spoken_utterance(utterance)

        # 1. Non-visual query -> No perception needed
        if intent == SpokenVisualIntentType.NON_VISUAL:
            return VoicePerceptionResolution(
                intent_type=intent,
                requires_perception=False,
                targeted_query=None,
                confidence=1.0,
            )

        # 2. Change Inquiry -> Check temporal tracker first to avoid unnecessary vision call
        if intent == SpokenVisualIntentType.CHANGE_INQUIRY and self.temporal_tracker is not None:
            recent_changes = self.temporal_tracker.get_recent_meaningful_changes(limit=3)
            if recent_changes:
                summary = "; ".join([c.description for c in recent_changes])
                return VoicePerceptionResolution(
                    intent_type=intent,
                    requires_perception=False,
                    resolved_context_summary=f"Recent desktop changes: {summary}",
                    confidence=0.95,
                )

        # 3. Historical Reference -> Check episodic memory first
        if intent == SpokenVisualIntentType.HISTORICAL_REFERENCE and self.episodic_memory is not None:
            facts = self.episodic_memory.query_facts(query=utterance, limit=2)
            if facts:
                return VoicePerceptionResolution(
                    intent_type=intent,
                    requires_perception=False,
                    resolved_context_summary=f"Episodic memory: {facts[0].fact_summary}",
                    confidence=0.9,
                )

        # 4. Error Investigation or Current Screen -> Check if current context already has high-confidence answer
        if current_screen_context is not None and not current_screen_context.is_error:
            if intent == SpokenVisualIntentType.ERROR_INVESTIGATION and current_screen_context.errors:
                return VoicePerceptionResolution(
                    intent_type=intent,
                    requires_perception=False,
                    resolved_context_summary=f"Identified error from current context: {current_screen_context.errors[0]}",
                    confidence=0.9,
                )
            if intent == SpokenVisualIntentType.CURRENT_SCREEN and current_screen_context.overall_confidence >= 0.85:
                return VoicePerceptionResolution(
                    intent_type=intent,
                    requires_perception=False,
                    resolved_context_summary=current_screen_context.summary,
                    confidence=current_screen_context.overall_confidence,
                )

        # 5. Otherwise, trigger targeted perception
        return VoicePerceptionResolution(
            intent_type=intent,
            requires_perception=True,
            targeted_query=utterance,
            confidence=0.85,
        )
