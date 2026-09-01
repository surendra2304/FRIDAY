"""Computer Action Proposal abstraction and safety classification models.

Defines proposal structures for mouse clicks, movements, typing, key presses, and scrolling
without executing any operating system or hardware actions. Enforces strict safety gating
where proposal != execution.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from friday.core.types import SafetyLevel


class ActionType(str, Enum):
    """Enumeration of proposed computer actions."""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    TYPE = "type"
    KEY_PRESS = "key_press"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    DRAG = "drag"


@dataclass
class ComputerActionProposal:
    """Read-only proposal for a computer action, isolated from OS execution."""

    action_type: ActionType
    arguments: dict[str, Any]
    intent: str
    risk_level: SafetyLevel = SafetyLevel.SENSITIVE
    requires_confirmation: bool = True
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_executed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize proposal to a structured dictionary."""
        return {
            "proposal_id": self.proposal_id,
            "action_type": self.action_type.value,
            "arguments": self.arguments,
            "intent": self.intent,
            "risk_level": self.risk_level.value,
            "requires_confirmation": self.requires_confirmation,
            "created_at": self.created_at.isoformat(),
            "is_executed": self.is_executed,
        }

    def format_for_user(self) -> str:
        """Format proposal cleanly for user authorization/confirmation."""
        args_str = ", ".join(f"{k}={v}" for k, v in self.arguments.items())
        return (
            f"[ACTION PROPOSAL: {self.action_type.value.upper()}]\n"
            f"- Intent: {self.intent}\n"
            f"- Arguments: {args_str}\n"
            f"- Risk Level: {self.risk_level.value}\n"
            f"- Confirmation Required: {self.requires_confirmation}\n"
            f"- Status: PROPOSED (NOT EXECUTED)"
        )


class ProposalBuilder:
    """Factory helper to construct safely classified ComputerActionProposal instances."""

    @staticmethod
    def click(x: int, y: int, intent: str, double: bool = False, right: bool = False) -> ComputerActionProposal:
        """Propose a mouse click at specific coordinates."""
        action = ActionType.DOUBLE_CLICK if double else (ActionType.RIGHT_CLICK if right else ActionType.CLICK)
        return ComputerActionProposal(
            action_type=action,
            arguments={"x": x, "y": y},
            intent=intent,
            risk_level=SafetyLevel.SENSITIVE,
            requires_confirmation=True,
        )

    @staticmethod
    def type_text(text: str, intent: str, is_sensitive_secret: bool = False) -> ComputerActionProposal:
        """Propose typing text."""
        # Typing commands, code, or terminal inputs is DANGEROUS / SENSITIVE
        risk = SafetyLevel.DANGEROUS if any(k in text.lower() for k in ["rm -rf", "format", "del /f", "drop table"]) else SafetyLevel.SENSITIVE
        return ComputerActionProposal(
            action_type=ActionType.TYPE,
            arguments={"text": text, "is_sensitive": is_sensitive_secret},
            intent=intent,
            risk_level=risk,
            requires_confirmation=True,
        )

    @staticmethod
    def key_press(key: str, intent: str) -> ComputerActionProposal:
        """Propose pressing a single key."""
        # Enter, Backspace, Delete, Escape have state-altering potential
        risk = SafetyLevel.DANGEROUS if key.lower() in ("enter", "return", "delete") else SafetyLevel.SENSITIVE
        return ComputerActionProposal(
            action_type=ActionType.KEY_PRESS,
            arguments={"key": key},
            intent=intent,
            risk_level=risk,
            requires_confirmation=True,
        )

    @staticmethod
    def hotkey(keys: list[str], intent: str) -> ComputerActionProposal:
        """Propose pressing a combination of keys (e.g. Ctrl+C, Alt+F4)."""
        keys_joined = "+".join(keys).lower()
        risk = SafetyLevel.DANGEROUS if any(k in keys_joined for k in ["alt+f4", "ctrl+w", "ctrl+alt+del", "win+r"]) else SafetyLevel.SENSITIVE
        return ComputerActionProposal(
            action_type=ActionType.HOTKEY,
            arguments={"keys": keys},
            intent=intent,
            risk_level=risk,
            requires_confirmation=True,
        )

    @staticmethod
    def scroll(delta_y: int, x: int | None = None, y: int | None = None, intent: str = "Scroll view") -> ComputerActionProposal:
        """Propose scrolling the viewport."""
        args: dict[str, Any] = {"delta_y": delta_y}
        if x is not None and y is not None:
            args["x"] = x
            args["y"] = y
        return ComputerActionProposal(
            action_type=ActionType.SCROLL,
            arguments=args,
            intent=intent,
            risk_level=SafetyLevel.SAFE,
            requires_confirmation=False,
        )
