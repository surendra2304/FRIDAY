from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import importlib
import platform


class Health(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True)
class Check:
    name: str
    state: Health
    details: str


@dataclass
class Report:
    overall: Health
    checks: list[Check]

    def as_dict(self):
        return {
            "overall": self.overall.value,
            "checks": [{"name": c.name, "state": c.state.value, "details": c.details} for c in self.checks],
        }


def build(modules=()):
    checks = [
        Check("python", Health.HEALTHY, platform.python_version()),
        Check("platform", Health.HEALTHY, platform.platform()),
    ]
    for m in modules:
        try:
            importlib.import_module(m)
            checks.append(Check(m, Health.HEALTHY, "imported"))
        except Exception as e:
            checks.append(Check(m, Health.DEGRADED, str(e)))
    overall = (
        Health.FAILED
        if any(c.state is Health.FAILED for c in checks)
        else Health.DEGRADED
        if any(c.state is Health.DEGRADED for c in checks)
        else Health.HEALTHY
    )
    return Report(overall, checks)
