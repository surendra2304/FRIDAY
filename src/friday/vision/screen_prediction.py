"""Screen Prediction and Context-Aware Workflow Suggestion Engine for FRIDAY."""

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("vision.screen_prediction")


class ScreenPredictionEngine:
    """Predicts user intentions and proactive suggestions based on screen text & window context."""

    def __init__(self):
        pass

    def analyze_screen_context(self, screen_text: str = "", active_window: str = "") -> list[dict[str, str]]:
        """Analyze visible screen content and generate proactive suggestions."""
        suggestions: list[dict[str, str]] = []
        text_lower = (screen_text or "").lower()
        win_lower = (active_window or "").lower()

        # 1. Error / Exception detection
        if any(w in text_lower for w in ["traceback (most recent call last):", "syntaxerror", "exception:", "error: [err"]):
            suggestions.append({
                "type": "error_resolution",
                "trigger": "code_error_detected",
                "suggestion": "I noticed an error traceback on screen. Would you like me to analyze and suggest a fix?",
            })

        # 2. Form / Input field detection
        if any(w in text_lower for w in ["first name", "last name", "email address", "submit", "sign up"]):
            suggestions.append({
                "type": "form_assistance",
                "trigger": "form_detected",
                "suggestion": "There appears to be a form on screen. Would you like assistance filling it out?",
            })

        # 3. Excel / Spreadsheet context
        if "excel" in win_lower or ".xlsx" in win_lower or "spreadsheet" in text_lower:
            suggestions.append({
                "type": "workflow_action",
                "trigger": "spreadsheet_open",
                "suggestion": "You have a spreadsheet open. Would you like me to calculate summaries or format data?",
            })

        # 4. Git / PR context
        if "pull request" in text_lower or "merge branch" in text_lower or "git status" in text_lower:
            suggestions.append({
                "type": "developer_action",
                "trigger": "git_workflow",
                "suggestion": "I see Git/PR activity on screen. Want me to review the diff or check commit status?",
            })

        return suggestions


class ScreenPredictionTool(BaseTool):
    """Tool for generating screen-based proactive predictions and suggestions."""

    name = "screen_prediction"
    description = (
        "Analyze visible screen text and active window title to generate proactive, "
        "context-aware suggestions and next actions."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "screen_text": {
                "type": "string",
                "description": "Visible text extracted from screen OCR.",
            },
            "active_window": {
                "type": "string",
                "description": "Active window title or application name.",
            },
        },
    }

    def __init__(self, engine: ScreenPredictionEngine | None = None):
        super().__init__()
        self.engine = engine or ScreenPredictionEngine()

    def execute(self, screen_text: str = "", active_window: str = "", **kwargs: Any) -> ToolResult:
        try:
            suggestions = self.engine.analyze_screen_context(screen_text=screen_text, active_window=active_window)
            if not suggestions:
                return ToolResult(
                    name=self.name,
                    content="Screen analysis complete. No specific proactive suggestions for current view.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            lines = [f"- {s['suggestion']}" for s in suggestions]
            content = "Proactive Screen Suggestions:\n" + "\n".join(lines)
            return ToolResult(name=self.name, content=content, is_error=False, safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Failed to generate screen predictions: {e}", is_error=True, safety_level=self.safety_level)
