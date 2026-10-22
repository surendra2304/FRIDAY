from __future__ import annotations
from dataclasses import dataclass
from ..contracts import PlanNode


@dataclass(frozen=True)
class Wave:
    index: int
    node_ids: tuple[str, ...]

    def parallel(self):
        return len(self.node_ids) > 1


def build_waves(nodes: list[PlanNode]) -> list[Wave]:
    remaining = {n.node_id: set(n.dependencies) for n in nodes}
    waves = []
    while remaining:
        ready = tuple(sorted(k for k, d in remaining.items() if not d))
        if not ready:
            raise ValueError("Cyclic plan")
        waves.append(Wave(len(waves), ready))
        rs = set(ready)
        for k in ready:
            remaining.pop(k)
        for deps in remaining.values():
            deps.difference_update(rs)
    return waves
