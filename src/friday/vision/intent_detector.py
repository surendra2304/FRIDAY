"""Intent detection for FRIDAY.

Detects whether a user request is a geometric deterministic action, a semantic UI action, or falls back to generic processing.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from friday.vision.detector import DeterministicActionDetector


class ActionIntent(Enum):
    GEOMETRIC_ACTION = "geometric_action"
    SEMANTIC_UI_ACTION = "semantic_ui_action"
    OTHER = "other"


@dataclass
class IntentResult:
    intent: ActionIntent
    confidence: float
    parsed_data: dict[str, Any] | None = None


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
        # Generic semantic element clicks: "click the send button", "click the File menu",
        # "click the search box", "click the submit link", "click the General tab".
        r"^(?:please )?(?:click|press|select|tap) (?:the )?(?P<target>.+?) (?:button|link|tab|menu|menu item|icon|box|field|checkbox|toggle)$": {
            "action_type": "click",
        },
        r"^(?:please )?(?:click|press|select|tap) (?:the )?(?P<target>[^ ]+)$": {
            "action_type": "click",
        },
    }

    # Known applications launchable deterministically without LLM/Vision.
    # Maps spoken app names to Windows executables for the UIA provider.
    APP_LAUNCH_MAP = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "word": "winword.exe",
        "microsoft word": "winword.exe",
        "excel": "excel.exe",
        "microsoft excel": "excel.exe",
        "wordpad": "write.exe",
        "task manager": "taskmgr.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "powershell": "powershell.exe",
        "terminal": "wt.exe",
        "settings": "ms-settings:",
        "control panel": "control.exe",
        "microsoft store": "ms-windows-store:",
        "store": "ms-windows-store:",
    }

    LAUNCH_PATTERN = re.compile(
        r"^(?:please )?(?:open|launch|start|run) (?:the )?(?P<app>.+?)(?: (?:app|application|program|window))?$"
    )

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
            match = re.search(pattern, text)
            if match:
                parsed = dict(data)
                if "target" not in parsed and "target" in match.groupdict():
                    parsed["target"] = match.group("target").strip()
                return IntentResult(
                    intent=ActionIntent.SEMANTIC_UI_ACTION,
                    confidence=1.0,
                    parsed_data=parsed,
                )

        # 3. application launch – "open notepad", "launch calculator"
        launch_match = cls.LAUNCH_PATTERN.match(text)
        if launch_match:
            app = launch_match.group("app").strip()
            if app in cls.APP_LAUNCH_MAP:
                return IntentResult(
                    intent=ActionIntent.SEMANTIC_UI_ACTION,
                    confidence=1.0,
                    parsed_data={
                        "action_type": "launch",
                        "target": app,
                        "executable": cls.APP_LAUNCH_MAP[app],
                    },
                )

        # 4. fuzzy match – placeholder that could be integrated with the UI provider later.
        # For now we return OTHER to let the generic pipeline handle it.
        return IntentResult(intent=ActionIntent.OTHER, confidence=0.0, parsed_data=None)
