"""Dictionary Tool for word definitions, phonetics, synonyms, and spelling assistance."""

from __future__ import annotations

import difflib
import urllib.parse
from typing import Any

import httpx

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.dictionary")

_TIMEOUT = 8.0

# Common English vocabulary dictionary baseline for offline spelling check suggestions
COMMON_VOCAB = {
    "accommodation",
    "embarrassment",
    "millennium",
    "occurrence",
    "maintenance",
    "pronunciation",
    "privilege",
    "rhythm",
    "recommend",
    "separate",
    "definitely",
    "weather",
    "whether",
    "ephemeral",
    "recursion",
    "algorithm",
    "autonomous",
    "intelligence",
    "architecture",
    "synchronous",
    "asynchronous",
    "biometrics",
    "holographic",
}


class DictionaryTool(BaseTool):
    """Lookup English definitions, parts of speech, pronunciations, and spelling suggestions."""

    name = "dictionary"
    description = (
        "Look up definitions, pronunciation, synonyms, or correct spelling for any English word. "
        "Supports 'what does X mean?', 'define X', or 'how do you spell X?'"
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "word": {
                "type": "string",
                "description": "The English word to define or check spelling for.",
            },
            "action": {
                "type": "string",
                "enum": ["define", "spell_check"],
                "description": "Operation: 'define' for meaning/synonyms, 'spell_check' for correct spelling suggestions.",
            },
        },
        "required": ["word"],
    }

    def execute(self, word: str, action: str = "define", **kwargs: Any) -> ToolResult:
        target = (word or "").strip().lower()
        if not target:
            return ToolResult(
                name=self.name,
                content="Error: Word parameter is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        # Spell check request
        if action == "spell_check":
            matches = difflib.get_close_matches(target, list(COMMON_VOCAB), n=3, cutoff=0.6)
            if target in COMMON_VOCAB:
                return ToolResult(
                    name=self.name,
                    content=f"'{target}' is spelled correctly.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            elif matches:
                return ToolResult(
                    name=self.name,
                    content=f"Did you mean: {', '.join(matches)}?",
                    is_error=False,
                    safety_level=self.safety_level,
                )

        # Query Free Dictionary API
        encoded_word = urllib.parse.quote(target)
        api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{encoded_word}"

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(api_url)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    entry = data[0]
                    word_title = entry.get("word", target).capitalize()
                    phonetic = entry.get("phonetic", "")
                    phonetic_str = f" [{phonetic}]" if phonetic else ""

                    meanings_lines = [f"{word_title}{phonetic_str}:"]

                    for m in entry.get("meanings", []):
                        pos = m.get("partOfSpeech", "meaning").upper()
                        meanings_lines.append(f"\n• {pos}:")
                        for d_idx, d in enumerate(m.get("definitions", [])[:3], 1):
                            definition_text = d.get("definition", "")
                            example = d.get("example")
                            ex_str = f' (e.g. "{example}")' if example else ""
                            meanings_lines.append(f"  {d_idx}. {definition_text}{ex_str}")

                        synonyms = m.get("synonyms", [])
                        if synonyms:
                            meanings_lines.append(f"  Synonyms: {', '.join(synonyms[:5])}")

                    return ToolResult(
                        name=self.name,
                        content="\n".join(meanings_lines),
                        is_error=False,
                        safety_level=self.safety_level,
                    )

            # Word not found: provide spelling suggestions
            matches = difflib.get_close_matches(target, list(COMMON_VOCAB), n=3, cutoff=0.5)
            sugg_str = f" Did you mean: {', '.join(matches)}?" if matches else ""
            return ToolResult(
                name=self.name,
                content=f"No definition found for '{target}'.{sugg_str}",
                is_error=True,
                safety_level=self.safety_level,
            )

        except Exception as e:
            logger.error(f"Dictionary API error for '{target}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Could not reach dictionary service: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
