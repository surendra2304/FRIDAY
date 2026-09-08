from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    replacement: str = "[REDACTED]"


class SecretRedactor:
    """Central redaction policy shared by text, memory, logs and tool results."""

    def __init__(self):
        self.rules = (
            Rule("google", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
            Rule("openai_like", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
            Rule("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b")),
            Rule(
                "private_key",
                re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.I),
            ),
            Rule(
                "secret_assignment",
                re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*([^\s,;]+)"),
                r"\1=[REDACTED]",
            ),
        )

    def redact(self, text: str | None) -> str | None:
        if text is None:
            return None
        out = text
        for r in self.rules:
            out = r.pattern.sub(r.replacement, out)
        return out

    def any(self, v: Any) -> Any:
        if isinstance(v, str):
            return self.redact(v)
        if isinstance(v, list):
            return [self.any(x) for x in v]
        if isinstance(v, tuple):
            return tuple(self.any(x) for x in v)
        if isinstance(v, dict):
            return {k: self.any(x) for k, x in v.items()}
        return v

    def persistent(self, text: str | None, max_chars: int = 12000) -> str | None:
        if text is None:
            return None
        out = self.redact(text) or ""
        if len(out) > max_chars:
            out = out[:max_chars] + " … [TRUNCATED]"
        return out


DEFAULT = SecretRedactor()
