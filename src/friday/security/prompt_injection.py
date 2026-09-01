import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum, auto


class InjectionRisk(Enum):
    SAFE = auto()
    LOW_RISK = auto()
    MEDIUM_RISK = auto()
    HIGH_RISK = auto()
    BLOCKED = auto()


class SourceType(Enum):
    SCREEN = auto()
    WEB = auto()
    EMAIL = auto()
    CHAT = auto()
    VOICE = auto()
    OCR = auto()
    TOOL_OUTPUT = auto()
    CLIPBOARD = auto()
    APPLICATION = auto()
    DOCUMENT = auto()


def _hash_content(content: str) -> str:
    """Return a SHA‑256 hash of the content for audit logging.
    The raw content is never persisted in logs.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# High‑risk regex patterns – anything matching these will be BLOCKED.
_HIGH_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore previous instructions", re.IGNORECASE),
    re.compile(r"\[SYSTEM\].*", re.IGNORECASE),
    re.compile(r"\[USER\].*", re.IGNORECASE),
    re.compile(r"<script[\s\S]*?>[\s\S]*?<\/script>", re.IGNORECASE),
    re.compile(r"base64,?([A-Za-z0-9+/=]+)"),
    re.compile(r"\u200b|\u200c|\u200d|\u2060"),  # zero‑width chars
]

# Medium‑risk patterns – require explicit user confirmation.
_MEDIUM_RISK_PATTERNS: list[re.Pattern] = [
    re.compile(r"\\b(?:run|execute)\\b", re.IGNORECASE),
    re.compile(r"(?:https?:\/\/)?[\w.-]+\.[a-z]{2,}\/[\w\/?=&%#-]*", re.IGNORECASE),
]


@dataclass
class GuardResult:
    sanitized: str
    risk: InjectionRisk
    content_hash: str


class ExternalContentGuard:
    """Sanitise untrusted external content and classify injection risk.

    The guard normalises Unicode, strips zero‑width characters, checks against
    high‑ and medium‑risk patterns, and removes obvious instruction markers.
    """

    def __init__(self, source: SourceType):
        self.source = source

    def _normalize(self, text: str) -> str:
        # Unicode NFKC normalisation and removal of zero‑width characters
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[\u200b\u200c\u200d\u2060]", "", text)
        return text

    def _detect_risk(self, text: str) -> InjectionRisk:
        for pat in _HIGH_RISK_PATTERNS:
            if pat.search(text):
                return InjectionRisk.BLOCKED
        for pat in _MEDIUM_RISK_PATTERNS:
            if pat.search(text):
                return InjectionRisk.MEDIUM_RISK
        return InjectionRisk.SAFE

    def _strip_instruction_markers(self, text: str) -> str:
        # Simple heuristic: drop lines that start with known instruction prefixes.
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[SYSTEM]") or stripped.startswith("[USER]") or stripped.startswith("### INSTRUCTION:"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    def guard(self, raw_content: str) -> GuardResult:
        normalized = self._normalize(raw_content)
        risk = self._detect_risk(normalized)
        sanitized = "" if risk == InjectionRisk.BLOCKED else self._strip_instruction_markers(normalized)
        return GuardResult(sanitized=sanitized, risk=risk, content_hash=_hash_content(normalized))


def guard_content(source: SourceType, content: str) -> GuardResult:
    """Convenience wrapper used by callers throughout the code base."""
    return ExternalContentGuard(source).guard(content)
