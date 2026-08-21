# -*- coding: utf-8 -*-
"""Intent detection for FRIDAY.

Detects whether a user request is a geometric deterministic action, a semantic UI action, or falls back to generic processing.
"""

import difflib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from friday.vision.detector import DeterministicActionDetector


class ActionIntent(Enum):
    GEOMETRIC_ACTION = "geometric_action"
    SEMANTIC_UI_ACTION = "semantic_ui_action"
    OTHER = "other"


@dataclass
class IntentResult:
    intent: ActionIntent
    confidence: float
    parsed_data: Optional[Dict[str, Any]] = None


class IntentDetector:
    """High‑level intent detector used by the agent before any LLM call.

    It first checks the existing deterministic detector. If that fails it attempts
    a lightweight rule‑based semantic UI match. The semantic matcher uses a set of
    regex patterns for common UI actions (e.g., click the start button) and a
    fuzzy fallback that scores against UI element names.
    """

    # Simple patterns for known UI elements – can be extended.
    UI_ACTION_PATTERNS = {
        r"click the (windows )?start button": {"action_type": "click", "target": "Start"},
        r"open (the )?start menu": {"action_type": "click", "target": "Start"},
        r"press (the )?enter key": {"action_type": "key_press", "key": "enter"},
    }

    @classmethod
    def detect(cls, user_input: str) -> IntentResult:
        # 1. geometric fast‑path
        det_intent = DeterministicActionDetector.detect(user_input)
        if det_intent:
            return IntentResult(
                intent=ActionIntent.GEOMETRIC_ACTION,
                confidence=det_intent.confidence,
                parsed_data={
                    "action_type": det_intent.action_type,
                    "arguments": det_intent.arguments,
                },
            )

        # 2. semantic UI patterns – exact regex match gives confidence 1.0
        text = user_input.strip().lower()
        for pattern, data in cls.UI_ACTION_PATTERNS.items():
            if re.search(pattern, text):
                return IntentResult(
                    intent=ActionIntent.SEMANTIC_UI_ACTION,
                    confidence=1.0,
                    parsed_data=data,
                )

        # 3. fuzzy match – placeholder that could be integrated with the UI provider later.
        # For now we return OTHER to let the generic pipeline handle it.
        return IntentResult(intent=ActionIntent.OTHER, confidence=0.0, parsed_data=None)
