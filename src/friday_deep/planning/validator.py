from __future__ import annotations
from collections import defaultdict, deque
from ..contracts import PlanEnvelope


class PlanValidationError(ValueError):
    pass


def validate_plan(plan: PlanEnvelope, max_nodes: int = 64) -> PlanEnvelope:
    if not plan.goal.strip():
        raise PlanValidationError("Empty goal")
    if not plan.nodes:
        raise PlanValidationError("Empty plan")
    if len(plan.nodes) > max_nodes:
        raise PlanValidationError("Plan too large")
    ids = [n.node_id for n in plan.nodes]
    if len(ids) != len(set(ids)):
        raise PlanValidationError("Duplicate node ID")
    idset = set(ids)
    indegree = {}
    outgoing = defaultdict(list)
    for n in plan.nodes:
        if not n.title.strip() or not n.description.strip():
            raise PlanValidationError(f"Empty fields in {n.node_id}")
        if n.node_id in n.dependencies:
            raise PlanValidationError(f"Self dependency {n.node_id}")
        if len(n.dependencies) != len(set(n.dependencies)):
            raise PlanValidationError(f"Duplicate dependency {n.node_id}")
        unknown = set(n.dependencies) - idset
        if unknown:
            raise PlanValidationError(f"Unknown dependency {sorted(unknown)}")
        indegree[n.node_id] = len(n.dependencies)
        for d in n.dependencies:
            outgoing[d].append(n.node_id)
    q = deque(sorted(k for k, v in indegree.items() if v == 0))
    seen = 0
    while q:
        x = q.popleft()
        seen += 1
        for child in sorted(outgoing[x]):
            indegree[child] -= 1
            if indegree[child] == 0:
                q.append(child)
    if seen != len(plan.nodes):
        raise PlanValidationError("Dependency graph contains a cycle")
    return plan
