from dataclasses import dataclass
import time


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_steps: int = 64
    max_tools: int = 128
    max_failures: int = 8
    max_seconds: float = 900.0
    steps: int = 0
    tools: int = 0
    failures: int = 0
    started: float = 0.0

    def start(self):
        self.started = time.monotonic()

    @property
    def elapsed(self):
        return 0.0 if not self.started else time.monotonic() - self.started

    def check(self):
        if self.steps >= self.max_steps:
            raise BudgetExceeded("step budget exhausted")
        if self.tools >= self.max_tools:
            raise BudgetExceeded("tool budget exhausted")
        if self.failures > self.max_failures:
            raise BudgetExceeded("failure budget exhausted")
        if self.started and self.elapsed >= self.max_seconds:
            raise BudgetExceeded("wall-clock budget exhausted")

    def step(self):
        self.check()
        self.steps += 1

    def tool(self):
        self.tools += 1
        self.check()

    def failure(self):
        self.failures += 1
        self.check()
