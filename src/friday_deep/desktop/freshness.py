from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenSnapshot:
    screen_hash: str
    width: int
    height: int
    captured_at: float


@dataclass(frozen=True)
class FreshnessResult:
    fresh: bool
    reason: str


class ScreenFreshness:
    def hash_metadata(self, metadata: dict) -> str:
        return hashlib.sha256(json.dumps(metadata, sort_keys=True, default=str).encode()).hexdigest()

    def compare(self, expected: str, current: str) -> FreshnessResult:
        if not expected or not current:
            return FreshnessResult(False, "missing environment hash")
        return FreshnessResult(
            expected == current,
            "environment hash matches" if expected == current else "environment changed; re-grounding required",
        )
