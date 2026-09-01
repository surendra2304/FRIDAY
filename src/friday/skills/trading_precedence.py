"""Trading Command Precedence and Safety Invariants.

Defines immutable authority hierarchy for all trading operations:
    1. Safety Gates (in Trading Bot) [Level 100 - Highest Authority]
    2. FRIDAY Commands (Supervisor / Manual Override / Panic) [Level 50]
    3. AI-Universe Recommendations (Advisory Signals) [Level 10 - Lowest Authority]

Invariant Contract:
- FRIDAY commands can override AI-Universe advisory recommendations (e.g. Reject, Cancel, Override).
- FRIDAY commands can NEVER override or bypass the Trading Bot's hardcoded safety gates
  (e.g., max drawdown, risk per trade, max leverage, testnet isolation).
- Emergency panic commands from FRIDAY route to the Trading Bot's OWN kill-switch API (/api/panic).
"""

from enum import IntEnum
from typing import Any


class CommandPrecedence(IntEnum):
    """Immutable command precedence hierarchy levels."""
    SAFETY_GATES = 100
    FRIDAY_COMMANDS = 50
    AI_UNIVERSE_RECOMMENDATIONS = 10


PRECEDENCE_SAFETY_GATES = CommandPrecedence.SAFETY_GATES
PRECEDENCE_FRIDAY_COMMANDS = CommandPrecedence.FRIDAY_COMMANDS
PRECEDENCE_AI_UNIVERSE_RECOMMENDATIONS = CommandPrecedence.AI_UNIVERSE_RECOMMENDATIONS

COMMAND_PRECEDENCE_HIERARCHY: list[str] = [
    "SAFETY_GATES",
    "FRIDAY_COMMANDS",
    "AI_UNIVERSE_RECOMMENDATIONS",
]


def tag_trading_command(
    command_name: str,
    precedence_level: CommandPrecedence = CommandPrecedence.FRIDAY_COMMANDS,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tag an outbound trading command with its precedence level and audit metadata.

    Args:
        command_name: Name of the command being issued (e.g., 'trigger_panic', 'override_advisory').
        precedence_level: The authority level of the command sender.
        metadata: Optional additional contextual attributes.

    Returns:
        Structured dictionary containing command envelope and precedence metadata.
    """
    payload = {
        "command": command_name,
        "precedence_level": int(precedence_level),
        "precedence_name": precedence_level.name,
        "immutable_hierarchy": COMMAND_PRECEDENCE_HIERARCHY,
        "can_override_ai_advisory": precedence_level >= CommandPrecedence.FRIDAY_COMMANDS,
        "can_bypass_bot_safety_gates": False,  # IMMUTABLE: Always False
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def validate_precedence_invariants(target_action: str) -> bool:
    """Validate that a requested action respects the invariant that safety gates cannot be bypassed.

    Returns:
        True if action is compliant with immutable safety precedence; False if action attempts bypass.
    """
    forbidden_bypass_keywords = [
        "bypass_safety",
        "disable_safety_gates",
        "override_risk_limits",
        "force_live_trading",
        "ignore_drawdown_limit",
    ]
    action_lower = target_action.lower()
    for kw in forbidden_bypass_keywords:
        if kw in action_lower:
            return False
    return True
