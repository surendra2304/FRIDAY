from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import importlib
import os


class AStatus(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


@dataclass
class CaseResult:
    name: str
    status: AStatus
    evidence: str = ""


@dataclass
class Report:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def overall(self):
        if any(c.status is AStatus.FAIL for c in self.cases):
            return "FAILED"
        if any(c.status is AStatus.BLOCKED for c in self.cases):
            return "BLOCKED_EXTERNAL"
        if any(c.status is AStatus.NOT_TESTED for c in self.cases):
            return "UNVERIFIED"
        return "VERIFIED"


def run():
    r = Report()
    for m in ("friday.agent.agent", "friday.tools.registry", "friday.core.types"):
        try:
            importlib.import_module(m)
            r.cases.append(CaseResult("import:" + m, AStatus.PASS, "imported"))
        except Exception as e:
            r.cases.append(CaseResult("import:" + m, AStatus.FAIL, str(e)))
    r.cases.append(
        CaseResult("windows_hardware", AStatus.BLOCKED if os.name != "nt" else AStatus.NOT_TESTED, "not executed here")
    )
    return r
