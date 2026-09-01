"""Memory retrieval and embedding decision policies for FRIDAY.

Provides testable, deterministic heuristics to ensure:
1. Retrieval is skipped for trivial turns (greetings, simple math, time queries, commands).
2. Retrieval is activated for factual, preference, architectural, and past context queries.
3. Embedding is skipped for low-value/transient content (greetings, acknowledgements, calculations).
4. Embedding is preserved for preferences, decisions, stable facts, and substantive explanations.
"""

from __future__ import annotations

import re

from friday.core.types import Message, Role

# Common greetings and conversational pleasantries (exact match or prefix)
GREETINGS: set[str] = {
    "hi",
    "hello",
    "hey",
    "hey friday",
    "hello friday",
    "hi friday",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "how are you",
    "how are you doing",
    "what's up",
    "whats up",
    "greetings",
}

# Trivial acknowledgements
ACKNOWLEDGEMENTS: set[str] = {
    "ok",
    "okay",
    "thanks",
    "thank you",
    "thank you very much",
    "thanks friday",
    "got it",
    "sure",
    "sounds good",
    "yes",
    "no",
    "yep",
    "nope",
    "alright",
    "understood",
}

# Simple one-word commands
TRIVIAL_COMMANDS: set[str] = {
    "stop",
    "stop.",
    "cancel",
    "cancel.",
    "exit",
    "quit",
    "clear",
    "bye",
    "goodbye",
    "pause",
    "resume",
    "help",
}

# Realtime time/date questions that require clock tools rather than memory
TIME_DATE_PATTERNS = [
    re.compile(r"^what\s+(time|is\s+the\s+time|day|is\s+today's?\s+date|is\s+the\s+date)\??$", re.IGNORECASE),
    re.compile(r"^(current\s+time|tell\s+me\s+the\s+time|what\s+time\s+is\s+it)\??$", re.IGNORECASE),
]

# Simple arithmetic expressions
MATH_PATTERN = re.compile(
    r"^(what\s+is\s+|calculate\s+|eval\s+)?[\d\.\s\+\-\*\/\%\^\(\)\=]+\??$",
    re.IGNORECASE,
)

# Strong signals for memory recall
MEMORY_SIGNALS = [
    "remember",
    "recall",
    "forget",
    "editor",
    "favorite",
    "preference",
    "decision",
    "decide",
    "project",
    "architecture",
    "config",
    "we discussed",
    "discussed",
    "earlier",
    "previous",
    "yesterday",
    "last time",
    "did i",
    "did we",
    "what is my",
    "what are my",
    "where is my",
    "who is my",
    "which",
    "how did we",
    "note",
]


def should_retrieve_memory(query: str) -> bool:
    """Determine whether a user turn warrants historical memory retrieval.

    Returns:
        bool: True if memory retrieval should be performed, False otherwise.
    """
    if not query:
        return False

    clean = query.strip()
    if len(clean) < 3:
        return False

    lower = clean.lower().rstrip("?.! ")

    # 1. Check greetings
    if lower in GREETINGS:
        return False

    # 2. Check acknowledgements and trivial commands
    if lower in ACKNOWLEDGEMENTS or lower in TRIVIAL_COMMANDS:
        return False

    # 3. Check realtime clock queries
    for pat in TIME_DATE_PATTERNS:
        if pat.match(clean):
            return False

    # 4. Check pure math (unless explicit memory keywords are present)
    has_memory_signal = any(sig in lower for sig in MEMORY_SIGNALS)
    if not has_memory_signal and MATH_PATTERN.match(clean) and any(c in clean for c in "+-*/%^"):
        return False

    # 5. Strong memory keywords always trigger retrieval
    if has_memory_signal:
        return True

    # 6. Short questions (< 4 words) without memory signals default to False to save latency
    words = clean.split()
    if len(words) < 4:
        return False

    # 7. Substantive conversational turns default to True
    return True


def should_embed_message(message: Message) -> bool:
    """Determine whether a message should be stored in the semantic vector index.

    Returns:
        bool: True if embedding should be generated and stored, False otherwise.
    """
    if not message.content:
        return False

    text = message.content.strip()
    if len(text) < 15:
        return False

    lower = text.lower().rstrip("?.! ")

    # Do not embed greetings or trivial acknowledgements
    if lower in GREETINGS or lower in ACKNOWLEDGEMENTS or lower in TRIVIAL_COMMANDS:
        return False

    # Do not embed pure clock or simple math queries/responses
    for pat in TIME_DATE_PATTERNS:
        if pat.match(text):
            return False

    if MATH_PATTERN.match(text) and any(c in text for c in "+-*/%^"):
        return False

    # Untrusted external observations (tool outputs, screen OCR, websites) must never automatically
    # become trusted long-term semantic memories or user preferences without explicit confirmation
    if getattr(message, "trust_level", None) == getattr(message.trust_level, "UNTRUSTED_EXTERNAL", "untrusted_external") or message.role == Role.TOOL:
        # Check if explicitly confirmed or tagged as trusted
        is_confirmed = message.metadata.get("user_confirmed", False) if hasattr(message, "metadata") and message.metadata else False
        if not is_confirmed:
            return False

    # Prevent prompt injection strings in text from being indexed into memory
    lower_check = lower
    if any(inj in lower_check for inj in ("ignore previous instructions", "system prompt", "developer mode", "override instructions", "you are now")):
        return False

    # Retain substantive messages
    words = text.split()
    return len(words) >= 3
