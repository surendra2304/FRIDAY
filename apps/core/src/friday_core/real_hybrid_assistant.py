"""Local-first assistant orchestration inspired by Jarvis's hybrid brain.

Providers and local actions are injected; this module never executes shell commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from typing import Callable


@dataclass(frozen=True)
class AssistantReply:
    text: str
    source: str
    model: str = ""


class HybridAssistantEngine:
    """Bounded conversational history, model failover and rate-limit cooldown."""

    def __init__(self, models: list[str], provider: Callable,
                 local_action: Callable[[str], str | None],
                 clock: Callable[[], float] = time.monotonic,
                 history_turns: int = 3) -> None:
        if history_turns < 0:
            raise ValueError("history_turns must be nonnegative")
        self.models = tuple(models)
        self.provider = provider
        self.local_action = local_action
        self.clock = clock
        self.history_turns = history_turns
        self.history: list[dict[str, str]] = []
        self.cooldown_until = 0.0

    @staticmethod
    def retry_delay(error: Exception) -> float:
        """Parse a Retry-After delta or Jarvis-style minute/second message."""
        headers = getattr(error, "headers", {}) or {}
        try:
            delay = float(headers.get("Retry-After", headers.get("retry-after", "nan")))
            if math.isfinite(delay) and delay >= 0:
                return delay
        except (TypeError, ValueError):
            delay = 60.0
        match = re.search(r"try again in\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", str(error).lower())
        return float(match[1] or 0) * 60 + float(match[2]) + 2 if match else 60.0

    def respond(self, query: str) -> AssistantReply:
        query = re.sub(r"^\s*(?:jarvis|friday)\b[,\s]*", "", query, flags=re.I).strip()
        if not query:
            raise ValueError("query must contain a command")
        local = self.local_action(query)
        if local:
            return AssistantReply(local, "local")
        if self.clock() >= self.cooldown_until:
            for model in self.models:
                messages = [dict(item) for item in self.history]
                messages.append({"role": "user", "content": query})
                try:
                    answer = self.provider(model, messages)
                    if not isinstance(answer, str) or not answer.strip():
                        continue
                except Exception as error:
                    limited = getattr(error, "status_code", None) == 429 or bool(
                        re.search(r"rate[ _-]?limit|too many requests|\b429\b", str(error), re.I))
                    if limited:
                        self.cooldown_until = max(self.cooldown_until, self.clock() + self.retry_delay(error))
                        break
                    continue
                self.history.extend([{"role": "user", "content": query},
                                     {"role": "assistant", "content": answer.strip()}])
                self.history = self.history[-2 * self.history_turns:] if self.history_turns else []
                return AssistantReply(answer.strip(), "cloud", model)
        return AssistantReply("Cloud unavailable; registered local actions remain available.", "fallback")
