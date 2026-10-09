"""Small language helpers shared by the fast paths and the device directive layer.

The one that matters here is :func:`is_compound_request`, and the bug it exists
to prevent is worth stating plainly.

FRIDAY short-circuits a lot of input without consulting a model: greetings,
"what time is it", "open notepad", "email Alice that ...". Each of those
detectors matches on a *substring*, because that is what makes them robust to
phrasing. That robustness is also the bug: a request that contains a recognised
phrase *anywhere* was answered as if it consisted only of that phrase.

    "please read the file called missing_file.txt and also tell me the current date"
        -> "Today is Wednesday, October 07, 2026."

The file was never read and nothing said so. A user asking for two things
received one of them and a confident tone. The same shape of failure hit
"what time is it and also send an email to a@b.com", where the send path ran and
the question was silently dropped.

So: a detector may only *claim* a turn when the request is a single instruction.
When :func:`is_compound_request` says otherwise, the fast paths decline and the
request continues to the cognitive loop, which can plan more than one step. This
is a heuristic, and deliberately a conservative one - it only reports a compound
request when there is an explicit joining word plus a second piece of work, so
it cannot quietly disable a fast path for ordinary single commands.
"""

from __future__ import annotations

import re

__all__ = ["is_compound_request", "second_clause"]

#: Words that introduce a second piece of work. "and" alone is deliberately
#: absent: "open notepad and chrome" is one action with two objects, and so is
#: "increase the volume and brightness". Only an explicit continuation, or an
#: "and"/"then" followed by a verb that starts new work, counts.
_CONTINUATION = re.compile(
    r"""
    \band\s+also\b
    | \band\s+then\b
    | \bthen\s+also\b
    | \bafter\s+that\b
    | \balso\s*,?\s*(?:please\s+)?(?:can|could|would|will)\s+you\b
    | \b(?:then|also)\s*,?\s+please\b
    | ;\s*\S
    | ,\s*then\s+\w
    | \band\s+(?:please\s+)?(?:
          read|write|send|email|mail|message|text|call|open|close|launch|start|stop
        | check|tell|show|list|create|delete|remove|add|set|make|run|search|find
        | calculate|compute|summari[sz]e|translate|remind|schedule|book|order
        | turn|play|pause|increase|decrease|raise|lower|mute|unmute|type|press
      )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Filler that carries no instruction, so a trailing "please" does not turn a
#: single request into a compound one.
_TRAILING_FILLER = re.compile(
    r"[\s,.]*(?:please|for me|now|thanks|thank you|right now|asap)\.?[\s,.]*$",
    re.IGNORECASE,
)


def second_clause(text: str) -> str | None:
    """Return the text from the first continuation marker, or ``None``.

    Useful for diagnostics: it names the part of the request a fast path would
    otherwise have dropped.
    """
    if not text:
        return None
    match = _CONTINUATION.search(text)
    return text[match.start():].strip() if match else None


def is_compound_request(text: str) -> bool:
    """True when *text* contains an explicit second instruction.

    Conservative by construction: conjunction-driven, not comma-driven, so
    ordinary phrasing such as "open notepad, please" or "volume up and
    brightness up" is not swept up.
    """
    if not text:
        return False
    stripped = _TRAILING_FILLER.sub("", text.strip())
    if not stripped:
        return False
    # More than one sentence is more than one instruction. The terminator has
    # to be followed by whitespace and a word: without that, the dot in
    # "alice@x.com" or "notes.txt" reads as a sentence break and every request
    # naming an address or a file becomes "compound".
    if len([s for s in re.split(r"[.!?]+\s+(?=[A-Za-z\"'(])", stripped.strip()) if s.strip()]) > 1:
        return True
    return _CONTINUATION.search(stripped) is not None
