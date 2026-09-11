from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from uuid import uuid4

from .contracts import ExecutionResult, PlanEnvelope, PlanNode, Status, Trust
from .memory.store import EphemeralStore, Record
from .planning.validator import validate_plan
from .runtime.state import State, TaskStateMachine
from .security.redaction import DEFAULT


@dataclass(frozen=True)
class MentorFeedback:
    node_id: str
    passed: bool
    observation: str = ""
    adjustment: str = ""
    retry_node: bool = False


@dataclass
class CollaborationRun:
    goal: str
    plan_id: str = ""
    status: Status = Status.PENDING
    revisions: int = 0
    results: list[ExecutionResult] = field(default_factory=list)
    feedback: list[MentorFeedback] = field(default_factory=list)
    state_history: list[State] = field(default_factory=list)


PlanFactory = Callable[[str, MentorFeedback | None, PlanEnvelope | None], PlanEnvelope]
Executor = Callable[[PlanNode], ExecutionResult]
Mentor = Callable[[PlanNode, ExecutionResult], MentorFeedback]


class CollaborationLoop:
    """Bounded Planner -> Specialist -> Mentor feedback loop.

    The loop keeps model output as structured data and never treats Mentor
    observations as executable instructions. Execution remains owned by the
    supplied executor and therefore by FRIDAY's existing safety boundary.
    """

    def __init__(
        self,
        planner: PlanFactory,
        executor: Executor,
        mentor: Mentor,
        memory: EphemeralStore | None = None,
        max_revisions: int = 3,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.mentor = mentor
        self.memory = memory or EphemeralStore()
        self.max_revisions = max(0, max_revisions)

    def run(self, goal: str) -> CollaborationRun:
        run = CollaborationRun(goal=goal)
        machine = TaskStateMachine()
        machine.transition(State.PLANNING, "Create initial structured plan")
        plan = validate_plan(self.planner(goal, None, None))
        run.plan_id = plan.plan_id
        completed: set[str] = set()
        feedback: MentorFeedback | None = None

        while True:
            pending = [node for node in self._ordered_nodes(plan) if node.node_id not in completed]
            if not pending:
                machine.transition(State.VERIFYING, "Mentor verified all planned nodes")
                machine.transition(State.SUCCEEDED, "Collaboration goal completed")
                run.status = Status.SUCCEEDED
                break

            node = pending[0]
            if any(dep not in completed for dep in node.dependencies):
                machine.transition(State.BLOCKED, f"Unmet dependency for {node.node_id}")
                run.status = Status.BLOCKED
                break

            machine.transition(State.EXECUTING, f"Execute {node.node_id}")
            result = self.executor(node)
            run.results.append(result)
            if result.status in (Status.WAITING_APPROVAL, Status.BLOCKED, Status.CANCELLED):
                run.status = result.status
                machine.transition(State.WAITING_APPROVAL if result.status is Status.WAITING_APPROVAL else State.BLOCKED, result.error or result.status.value)
                break

            machine.transition(State.VERIFYING, f"Mentor reviews {node.node_id}")
            review = self.mentor(node, result)
            run.feedback.append(review)
            self.memory.put(
                Record(
                    key=f"mentor:{run.plan_id}:{node.node_id}:{len(run.feedback)}",
                    content=review.observation,
                    trust=Trust.EXTERNAL,
                    metadata={"node_id": node.node_id, "passed": review.passed},
                )
            )

            if result.success and review.passed:
                completed.add(node.node_id)
                continue

            if run.revisions >= self.max_revisions:
                run.status = Status.FAILED
                machine.transition(State.FAILED, "Revision budget exhausted")
                break

            run.revisions += 1
            machine.transition(State.PLANNING, f"Revise plan after Mentor feedback for {node.node_id}")
            plan = validate_plan(self.planner(goal, review, plan))
            run.plan_id = plan.plan_id
            if review.retry_node:
                completed.discard(node.node_id)

        run.state_history = [State.NOT_STARTED] + [transition.new for transition in machine.history]
        return run

    @staticmethod
    def _ordered_nodes(plan: PlanEnvelope) -> list[PlanNode]:
        remaining = {node.node_id: node for node in plan.nodes}
        ordered: list[PlanNode] = []
        completed: set[str] = set()
        while remaining:
            ready = sorted(
                (node for node in remaining.values() if set(node.dependencies) <= completed),
                key=lambda node: node.node_id,
            )
            if not ready:
                raise ValueError("Plan cannot be ordered")
            for node in ready:
                ordered.append(node)
                completed.add(node.node_id)
                del remaining[node.node_id]
        return ordered
