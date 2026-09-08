from __future__ import annotations
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow_as_data"
    REVIEW = "require_review"
    BLOCK = "block"


@dataclass(frozen=True)
class Guarded:
    content: str
    source: str
    decision: Decision
    score: float
    content_hash: str
    reasons: tuple[str, ...] = ()


class ContentGuard:
    """Treat OCR/web/email/tool content as untrusted data, never instructions."""

    HARD = (
        re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.I),
        re.compile(r"\bdisregard\s+(?:the\s+)?system\s+prompt\b", re.I),
        re.compile(r"\bpretend\s+you\s+are\s+the\s+developer\b", re.I),
        re.compile(r"<script\b[\s\S]*?</script>", re.I),
        re.compile(r"\bformat\s+c:", re.I),
        re.compile(r"\b(?:export|dump)\s+(?:api[_ -]?keys?|credentials?)\b", re.I),
    )
    MEDIUM = (re.compile(r"\b(?:run|execute)\b", re.I), re.compile(r"\b(?:click|type|paste|press)\b", re.I))
    B64 = re.compile(r"(?is)(?:decode|execute|run|paste|eval).*?\bbase64\b.{0,64}[A-Za-z0-9+/]{100,}={0,2}")

    def guard(self, raw: str | None, source: str) -> Guarded:
        text = unicodedata.normalize("NFKC", raw or "")
        text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", text)
        hard = tuple(p.pattern for p in self.HARD if p.search(text))
        b64 = bool(self.B64.search(text))
        med = tuple(p.pattern for p in self.MEDIUM if p.search(text))
        if hard or b64:
            d, s = Decision.BLOCK, 1.0
            reasons = hard + (("suspicious_base64_payload",) if b64 else ())
            safe = ""
        elif med:
            d, s = Decision.REVIEW, 0.65
            reasons = med
            safe = text
        else:
            d, s = Decision.ALLOW, 0.0
            reasons = ()
            safe = text
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        return Guarded(safe, source, d, s, digest, reasons)

    def prompt_segment(self, raw: str, source: str) -> str:
        g = self.guard(raw, source)
        return f"[UNTRUSTED_{source.upper()} DATA hash={g.content_hash} risk={g.score:.2f}]\n{g.content}\n[/UNTRUSTED_{source.upper()} DATA]"
