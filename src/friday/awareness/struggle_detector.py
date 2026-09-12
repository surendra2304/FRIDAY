"""Struggle Detector — Behavioral Analysis and Stuck Detection.

Adapted from Jarvis awareness/struggle-detector.ts.
Detects when the user is actively working but encountering persistent friction or no progress:
- Repeated failing terminal commands, compiler errors, or tracebacks
- Trial-and-error editing cycles in VS Code
- Rapid undo/revert loops
- Unchanging failure states

100% Free, Local, and Offline: Evaluates active window metadata and text buffers
using local regex pattern matching and algorithmic metrics without any paid cloud APIs.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from friday.core.logging import get_logger

logger = get_logger("awareness.struggle_detector")


class AppCategory(str, Enum):
    CODE_EDITOR = "code_editor"
    TERMINAL = "terminal"
    BROWSER = "browser"
    CREATIVE_APP = "creative_app"
    GENERAL = "general"


@dataclass
class StruggleSignal:
    name: str
    score: float  # 0.0 - 1.0
    detail: str


@dataclass
class StruggleAnalysis:
    is_struggling: bool
    composite_score: float
    signals: list[StruggleSignal]
    app_category: AppCategory
    app_name: str
    window_title: str
    duration_ms: float
    error_summary: Optional[str] = None


@dataclass
class TextSnapshot:
    timestamp: float
    text_hash: str
    app_name: str
    output_hash: str
    dist_from_prev: int
    has_error: bool = False
    error_text: str = ""


# Application classification regexes
CODE_EDITORS = re.compile(
    r"\b(VS\s?Code|Visual Studio Code|Code|Cursor|PyCharm|IntelliJ|WebStorm|Sublime|Atom|vim|nvim|neovim|Zed|nano)\b",
    re.IGNORECASE,
)
TERMINALS = re.compile(
    r"\b(Terminal|Windows Terminal|PowerShell|pwsh|cmd\.exe|Command Prompt|bash|zsh|git bash|wt\.exe|iTerm|Warp)\b",
    re.IGNORECASE,
)
BROWSERS = re.compile(
    r"\b(Chrome|Google Chrome|Edge|Microsoft Edge|Firefox|Brave|Safari|Arc)\b",
    re.IGNORECASE,
)

# Common error patterns in code editors and terminals
ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Python Traceback", re.compile(r"Traceback \(most recent call last\):|^\s*File \".+\", line \d+|^\w+Error: .+", re.MULTILINE)),
    ("Syntax / Parse Error", re.compile(r"\bSyntaxError:|\bParseError:|\bunexpected token\b", re.IGNORECASE)),
    ("Compiler / Linker Error", re.compile(r"\berror:\s+|fatal error:|\bundefined reference to\b|\bcannot find symbol\b", re.IGNORECASE)),
    ("Uncaught Exception", re.compile(r"Uncaught (?:exception|error)|\bpanic:|\bUnhandledPromiseRejection\b", re.IGNORECASE)),
    ("Command Not Found", re.compile(r"is not recognized as an internal or external command|\bcommand not found\b|no such file or directory", re.IGNORECASE)),
    ("Git Conflict", re.compile(r"<{7}\s*HEAD|={7}\n|>{7}\s*", re.MULTILINE)),
    ("HTTP / Connection Error", re.compile(r"ECONNREFUSED|ETIMEDOUT|HTTP 500|HTTP 502|HTTP 503|HTTP 504", re.IGNORECASE)),
]


def classify_app(app_name: str, window_title: str = "") -> AppCategory:
    """Classify the application into an AppCategory based on name and title."""
    combined = f"{app_name} {window_title}"
    if CODE_EDITORS.search(combined):
        return AppCategory.CODE_EDITOR
    if TERMINALS.search(combined):
        return AppCategory.TERMINAL
    if BROWSERS.search(combined):
        return AppCategory.BROWSER
    return AppCategory.GENERAL


def simple_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def cheap_distance(a: str, b: str) -> int:
    """Fast length-difference heuristic distance without O(N*M) Levenshtein penalty."""
    if a == b:
        return 0
    return abs(len(a) - len(b)) + sum(1 for c1, c2 in zip(a[:100], b[:100]) if c1 != c2)


class StruggleDetector:
    """Evaluates text captures and active window states for struggle signals."""

    def __init__(
        self,
        grace_s: float = 60.0,
        cooldown_s: float = 90.0,
        struggle_threshold: float = 0.5,
    ) -> None:
        self.grace_s = grace_s
        self.cooldown_s = cooldown_s
        self.struggle_threshold = struggle_threshold

        self.snapshots: list[TextSnapshot] = []
        self.last_text: Optional[str] = None
        self.last_struggle_emit_at: float = 0.0
        self.struggle_started_at: Optional[float] = None

    def scan_errors(self, text: str) -> tuple[bool, str]:
        """Check if the text contains recognizable programming/terminal error patterns."""
        if not text:
            return False, ""
        for name, pattern in ERROR_PATTERNS:
            match = pattern.search(text)
            if match:
                matched_line = match.group(0).strip()
                return True, f"{name}: {matched_line[:80]}"
        return False, ""

    def evaluate(
        self,
        text: str,
        app_name: str,
        window_title: str = "",
        timestamp: Optional[float] = None,
    ) -> Optional[StruggleAnalysis]:
        """Evaluate a text capture from active editor, terminal, or window.

        Returns:
            StruggleAnalysis if struggle threshold is exceeded and cooldown expired.
            None otherwise.
        """
        now = timestamp if timestamp is not None else time.monotonic()
        app_cat = classify_app(app_name, window_title)

        has_err, err_summary = self.scan_errors(text)
        t_hash = simple_hash(text)
        out_hash = simple_hash(text[-500:] if len(text) > 500 else text)

        dist = cheap_distance(self.last_text or "", text)
        self.snapshots.append(
            TextSnapshot(
                timestamp=now,
                text_hash=t_hash,
                app_name=app_name,
                output_hash=out_hash,
                dist_from_prev=dist,
                has_error=has_err,
                error_text=err_summary,
            )
        )
        self.last_text = text

        # Keep rolling window of past 25 snapshots (up to ~3 minutes)
        if len(self.snapshots) > 25:
            self.snapshots.pop(0)

        # Require at least 3 snapshots before behavioral analysis
        if len(self.snapshots) < 3:
            return None

        # Calculate struggle signals
        signals: list[StruggleSignal] = []

        # Signal 1: Persistent or Repeated Errors (Weight 0.35)
        error_count = sum(1 for s in self.snapshots[-6:] if s.has_error)
        err_ratio = min(1.0, error_count / min(len(self.snapshots), 6))
        if err_ratio > 0.3:
            signals.append(
                StruggleSignal(
                    name="persistent_errors",
                    score=err_ratio,
                    detail=err_summary or "Repeated errors detected in active workspace",
                )
            )

        # Signal 2: Repeated Output Loops (Weight 0.25)
        recent_hashes = [s.output_hash for s in self.snapshots[-6:]]
        if len(recent_hashes) >= 4 and len(set(recent_hashes)) <= 2:
            signals.append(
                StruggleSignal(
                    name="repeated_output",
                    score=0.8,
                    detail="Identical terminal or compiler output across multiple runs",
                )
            )

        # Signal 3: Trial-and-Error Editing / Low Progress (Weight 0.25)
        text_hashes = [s.text_hash for s in self.snapshots[-6:]]
        if len(text_hashes) >= 5 and len(set(text_hashes)) <= 3:
            signals.append(
                StruggleSignal(
                    name="trial_and_error",
                    score=0.7,
                    detail="Frequent edits oscillating around the same code section",
                )
            )

        # Calculate composite score
        composite = 0.0
        if signals:
            composite = sum(s.score for s in signals) / max(len(signals), 1)

        is_struggling = composite >= self.struggle_threshold

        # Grace period & cooldown tracking
        if is_struggling:
            if self.struggle_started_at is None:
                self.struggle_started_at = now

            duration_ms = (now - self.struggle_started_at) * 1000.0

            # Allow immediate firing if explicit high-confidence error
            can_fire = (now - self.last_struggle_emit_at) >= self.cooldown_s
            past_grace = (now - self.struggle_started_at) >= self.grace_s or has_err

            if can_fire and past_grace:
                self.last_struggle_emit_at = now
                logger.info(
                    "Struggle detected (score=%.2f, app=%s): %s",
                    composite,
                    app_name,
                    err_summary,
                )
                return StruggleAnalysis(
                    is_struggling=True,
                    composite_score=composite,
                    signals=signals,
                    app_category=app_cat,
                    app_name=app_name,
                    window_title=window_title,
                    duration_ms=duration_ms,
                    error_summary=err_summary or (signals[0].detail if signals else "Workspace friction"),
                )
        else:
            self.struggle_started_at = None

        return None
