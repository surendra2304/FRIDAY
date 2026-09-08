from __future__ import annotations
from dataclasses import dataclass
from time import perf_counter


@dataclass(frozen=True)
class Case:
    id: str
    description: str
    expected: str
    fn: object


@dataclass(frozen=True)
class Result:
    id: str
    passed: bool
    expected: str
    actual: str
    elapsed_ms: float
    error: str | None = None


class Runner:
    def run(self, cases):
        out = []
        for c in cases:
            t = perf_counter()
            try:
                actual = c.fn()
                out.append(Result(c.id, actual == c.expected, c.expected, actual, (perf_counter() - t) * 1000))
            except Exception as e:
                out.append(Result(c.id, False, c.expected, "ERROR", (perf_counter() - t) * 1000, str(e)))
        return out
