"""Proposal-only tool for suggesting desktop computer actions without execution."""

from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder


class ProposeComputerActionTool(BaseTool):
    """SAFE Tool to formulate and validate computer action proposals without executing them."""

    name = "propose_computer_action"
    description = "Propose a computer action (click, type, scroll, key_press) with required confirmation gating without executing it."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["click", "double_click", "right_click", "move", "type", "key_press", "hotkey", "scroll"],
                "description": "Type of action proposed",
            },
            "intent": {
                "type": "string",
                "description": "Plain-text explanation of what this action intends to accomplish",
            },
            "x": {
                "type": "integer",
                "description": "Target X pixel coordinate on screen (for clicks/moves). Omit for automatic screen centering if intent specifies 'center'.",
            },
            "y": {
                "type": "integer",
                "description": "Target Y pixel coordinate on screen (for clicks/moves). Omit for automatic screen centering if intent specifies 'center'.",
            },
            "text": {
                "type": "string",
                "description": "Text to type (for type action)",
            },
            "key": {
                "type": "string",
                "description": "Key or hotkey to press",
            },
            "delta_y": {
                "type": "integer",
                "description": "Vertical scroll delta (positive=down, negative=up)",
            },
        },
        "required": ["action_type", "intent"],
    }

    def __init__(self) -> None:
        super().__init__()
        self.last_proposal: ComputerActionProposal | None = None

    def execute(
        self,
        action_type: str,
        intent: str,
        x: int | None = None,
        y: int | None = None,
        text: str | None = None,
        key: str | None = None,
        delta_y: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Construct action proposal safely. Never invokes OS input synthesis."""
        try:
            act_enum = ActionType(action_type.lower())
        except ValueError:
            return ToolResult(
                name=self.name,
                content=f"Invalid action_type: '{action_type}'. Supported: {[a.value for a in ActionType]}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if x is None and y is None and "center" in intent.lower():
            try:
                from friday.vision.windows_screen import WindowsScreenCaptureProvider
                displays = WindowsScreenCaptureProvider().list_displays()
                if displays:
                    x = int(displays[0].get("x", 0)) + int(displays[0]["width"]) // 2
                    y = int(displays[0].get("y", 0)) + int(displays[0]["height"]) // 2
                else:
                    x = 1920 // 2
                    y = 1080 // 2
            except Exception:
                x = 1920 // 2
                y = 1080 // 2

        proposal: ComputerActionProposal
        if act_enum in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            if x is None or y is None:
                return ToolResult(
                    name=self.name,
                    content="Missing 'x' or 'y' pixel coordinates for mouse click proposal.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            proposal = ProposalBuilder.click(
                x=int(x),
                y=int(y),
                intent=intent,
                double=(act_enum == ActionType.DOUBLE_CLICK),
                right=(act_enum == ActionType.RIGHT_CLICK),
            )

        elif act_enum == ActionType.TYPE:
            if not text:
                return ToolResult(
                    name=self.name,
                    content="Missing 'text' argument for typing proposal.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            proposal = ProposalBuilder.type_text(text=text, intent=intent)

        elif act_enum == ActionType.KEY_PRESS:
            if not key:
                return ToolResult(
                    name=self.name,
                    content="Missing 'key' argument for key press proposal.",
                    is_error=True,
                    safety_level=self.safety_level,
                )
            proposal = ProposalBuilder.key_press(key=key, intent=intent)

        elif act_enum == ActionType.HOTKEY:
            keys = [k.strip() for k in (key or "").split("+") if k.strip()]
            proposal = ProposalBuilder.hotkey(keys=keys, intent=intent)

        elif act_enum == ActionType.SCROLL:
            proposal = ProposalBuilder.scroll(delta_y=delta_y or 100, x=x, y=y, intent=intent)

        else:
            proposal = ComputerActionProposal(
                action_type=act_enum,
                arguments={"x": x, "y": y},
                intent=intent,
                risk_level=SafetyLevel.SENSITIVE,
                requires_confirmation=True,
            )

        self.last_proposal = proposal

        # Format user-facing proposal declaration
        output = proposal.format_for_user()
        return ToolResult(
            name=self.name,
            content=output,
            is_error=False,
            safety_level=self.safety_level,
        )
