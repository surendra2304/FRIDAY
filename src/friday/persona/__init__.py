"""FRIDAY signature communications persona.

This package adds a personality layer on top of FRIDAY's existing capability
and safety stack. It does not change routing, authorization, or tool logic —
it only shapes *how* FRIDAY speaks (text and voice) so that interactions feel
like a calm, dry-witted, quietly confident elite assistant rather than a
generic call-centre bot.

The blocks are strictly additive: every phrase that existing tests guarantee
("Calm, intelligent, concise, confident, natural", the greeting rule, the
provider-agnostic identity rules, etc.) remains untouched in the base prompts;
persona blocks are appended on top.
"""

from friday.persona.friday import (
    CLASSIC_GREETING_RESPONSES,
    FRIDAY_EMPTY_TURN_RESPONSE,
    FRIDAY_GREETING_RESPONSES,
    FRIDAY_TEXT_BLOCK,
    FRIDAY_VOICE_BLOCK,
    greeting_responses_for,
    proactive_style,
)

__all__ = [
    "CLASSIC_GREETING_RESPONSES",
    "FRIDAY_EMPTY_TURN_RESPONSE",
    "FRIDAY_GREETING_RESPONSES",
    "FRIDAY_TEXT_BLOCK",
    "FRIDAY_VOICE_BLOCK",
    "greeting_responses_for",
    "idle_style",
    "proactive_style",
]


def idle_style(persona: str, user_name: str) -> str:
    """Return the empty-turn ('FRIDAY is listening') response for a persona."""
    if persona == "friday":
        return FRIDAY_EMPTY_TURN_RESPONSE.format(user_name=user_name)
    return f"I'm listening. How can I assist you today, {user_name}?"