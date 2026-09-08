from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    TRANSIENT = "transient"
    AUTH = "authorization"
    SECURITY = "security"
    DATA = "data"
    TOOL = "tool"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RecoveryPlan:
    cls: FailureClass
    retry: bool
    escalate: bool
    fallback_tool: str | None = None
    reason: str = ""


class RecoveryPolicy:
    def classify(self, error: str) -> FailureClass:
        x = error.lower()
        if any(s in x for s in ("timeout", "503", "rate limit", "temporar")):
            return FailureClass.TRANSIENT
        if "authorization" in x or "permission" in x:
            return FailureClass.AUTH
        if any(s in x for s in ("security", "prompt injection", "hard block", "credential")):
            return FailureClass.SECURITY
        if any(s in x for s in ("invalid argument", "schema", "parse")):
            return FailureClass.DATA
        if "tool" in x:
            return FailureClass.TOOL
        return FailureClass.UNKNOWN

    def decide(self, error: str, attempt: int, max_attempts: int) -> RecoveryPlan:
        cls = self.classify(error)
        if cls in {FailureClass.AUTH, FailureClass.SECURITY}:
            return RecoveryPlan(cls, False, True, reason="Cannot recover around a safety or authorization boundary.")
        if cls is FailureClass.TRANSIENT and attempt < max_attempts:
            return RecoveryPlan(cls, True, False, reason="Transient failure may be retried within the bounded budget.")
        if cls is FailureClass.TOOL:
            return RecoveryPlan(
                cls, False, True, reason="Tool failure requires diagnosis or a pre-authorized fallback."
            )
        return RecoveryPlan(cls, False, True, reason="No safe automatic recovery available.")
