from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic


class State(str, Enum):
    NOT_STARTED = "not_started"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


TRANSITIONS = {
    State.NOT_STARTED: {State.PLANNING, State.BLOCKED, State.CANCELLED},
    State.PLANNING: {State.EXECUTING, State.WAITING_APPROVAL, State.BLOCKED, State.FAILED, State.CANCELLED},
    State.EXECUTING: {
        State.VERIFYING,
        State.WAITING_APPROVAL,
        State.PAUSED,
        State.FAILED,
        State.BLOCKED,
        State.CANCELLED,
        State.INCOMPLETE,
    },
    State.VERIFYING: {State.SUCCEEDED, State.PLANNING, State.FAILED, State.BLOCKED, State.INCOMPLETE},
    State.WAITING_APPROVAL: {State.EXECUTING, State.BLOCKED, State.CANCELLED},
    State.PAUSED: {State.EXECUTING, State.CANCELLED, State.BLOCKED},
    State.SUCCEEDED: set(),
    State.FAILED: set(),
    State.BLOCKED: set(),
    State.CANCELLED: set(),
    State.INCOMPLETE: set(),
}


@dataclass
class Transition:
    old: State
    new: State
    reason: str
    at: float = field(default_factory=monotonic)


@dataclass
class TaskStateMachine:
    state: State = State.NOT_STARTED
    history: list[Transition] = field(default_factory=list)

    def transition(self, new: State, reason: str = ""):
        if new != self.state and new not in TRANSITIONS[self.state]:
            raise ValueError(f"Illegal transition {self.state.value}->{new.value}")
        old = self.state
        self.state = new
        self.history.append(Transition(old, new, reason))
        return new

    @property
    def terminal(self):
        return self.state in {State.SUCCEEDED, State.FAILED, State.BLOCKED, State.CANCELLED, State.INCOMPLETE}

    @property
    def can_execute(self):
        return self.state is State.EXECUTING
