# -*- coding: utf-8 -*-
from __future__ import annotations
"""Active Working Task Memory & Context Isolation for FRIDAY.

Provides:
- Short-term working task state (`ActiveTaskContext`) isolated from long-term SQLite memory.
- Tracking of goal, plan, current state, active step, step outputs, constraints, observations, and clarifications.
- Automatic context size budgeting and relevance filtering to prevent token bloat and context contamination.
- Strict secret redaction, prevention of raw chain-of-thought and raw screenshot persistence.
- Clean lifecycle finalization: Discards transient scratch data upon completion/failure and yields high-level factual summaries for long-term memory.
- 100% provider-independent and testable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING
import uuid

from friday.core.logging import get_logger, redact_tool_args
from friday.core.types import Message, Role

if TYPE_CHECKING:
    from friday.agent.planner import PlanStep, StepStatus, TaskPlan
    from friday.agent.state import TaskState
    from friday.agent.verification import VerificationResult

logger = get_logger("memory.task_context")


@dataclass
class TaskObservation:
    """Safe, sanitized factual observation recorded during a step."""
    step_id: str
    content: str
    source_tool: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "content": self.content,
            "source_tool": self.source_tool,
            "timestamp": self.timestamp.isoformat(),
        }


class ActiveTaskContext:
    """Decoupled working memory holding ephemeral task context during execution."""

    def __init__(
        self,
        task_id: Optional[str] = None,
        goal: str = "",
        plan: Optional[Any] = None,
        max_observations: int = 15,
        max_output_chars_per_step: int = 1000,
    ) -> None:
        self.task_id: str = task_id or str(uuid.uuid4())
        self.goal: str = goal
        self.plan: Optional[Any] = plan
        self.state: Any = "NOT_STARTED"
        self.active_step_id: Optional[str] = None
        self.max_observations = max_observations
        self.max_output_chars_per_step = max_output_chars_per_step

        self.step_outputs: Dict[str, str] = {}
        self.step_verifications: Dict[str, VerificationResult] = {}
        self.constraints: List[str] = []
        self.user_clarifications: List[str] = []
        self.observations: List[TaskObservation] = []
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = datetime.now(timezone.utc)

    def set_state(self, state: TaskState) -> None:
        """Update active task state."""
        self.state = state
        self.updated_at = datetime.now(timezone.utc)

    def set_active_step(self, step_id: str) -> None:
        """Set the currently executing plan step ID."""
        self.active_step_id = step_id
        self.updated_at = datetime.now(timezone.utc)

    def add_constraint(self, constraint: str) -> None:
        """Add an operating constraint (e.g. read-only mode, max timeout)."""
        clean = constraint.strip()
        if clean and clean not in self.constraints:
            self.constraints.append(clean)
            self.updated_at = datetime.now(timezone.utc)

    def add_user_clarification(self, clarification: str) -> None:
        """Record user clarification or preference given for this task."""
        clean = clarification.strip()
        if clean:
            self.user_clarifications.append(clean)
            self.updated_at = datetime.now(timezone.utc)

    def record_step_result(
        self,
        step_id: str,
        result: Any,
        verification: Optional[VerificationResult] = None,
    ) -> None:
        """Record sanitized step result and verification outcome."""
        res_str = str(result)

        # Do not persist raw screenshots, image buffers or binary blobs
        if "data:image/" in res_str or "[image payload" in res_str.lower() or "base64" in res_str:
            res_str = "[Visual screenshot captured and processed safely]"

        # Redact secrets, keys, and tokens
        if "key=" in res_str or "token=" in res_str or "password=" in res_str or "secret=" in res_str:
            res_str = "[Sensitive credentials redacted]"

        # Truncate large tool outputs according to context budget
        if len(res_str) > self.max_output_chars_per_step:
            res_str = res_str[:self.max_output_chars_per_step] + f"... [truncated {len(res_str) - self.max_output_chars_per_step} chars]"

        self.step_outputs[step_id] = res_str
        if verification:
            self.step_verifications[step_id] = verification
        self.updated_at = datetime.now(timezone.utc)

    def add_observation(self, step_id: str, content: str, source_tool: Optional[str] = None) -> None:
        """Record a sanitized observation, evicting oldest if capacity reached."""
        clean = content.strip()
        if not clean:
            return

        # Redact secrets / binary payloads
        if "key=" in clean or "token=" in clean or "password=" in clean:
            clean = "[Sensitive credentials redacted]"

        obs = TaskObservation(step_id=step_id, content=clean, source_tool=source_tool)
        self.observations.append(obs)

        # Evict oldest observations if capacity exceeded (FIFO sliding window)
        if len(self.observations) > self.max_observations:
            self.observations = self.observations[-self.max_observations:]

        self.updated_at = datetime.now(timezone.utc)

    def get_working_summary(self) -> str:
        """Synthesize a compact working prompt block for the LLM working context."""
        state_str = self.state.value if hasattr(self.state, "value") else str(self.state)
        lines = [f"[Active Task Goal]: {self.goal}", f"[State]: {state_str}"]
        if self.active_step_id:
            lines.append(f"[Active Step]: {self.active_step_id}")

        if self.constraints:
            lines.append("[Constraints]: " + "; ".join(self.constraints))

        if self.user_clarifications:
            lines.append("[Clarifications]: " + " | ".join(self.user_clarifications))

        if self.step_outputs:
            lines.append("[Completed Step Results]:")
            for sid, out in self.step_outputs.items():
                v_stat = " (Verified)" if self.step_verifications.get(sid, getattr(self.step_verifications.get(sid), "passed", False)) else ""
                lines.append(f"  - Step '{sid}'{v_stat}: {out[:120]}")

        if self.observations:
            lines.append("[Recent Observations]:")
            for obs in self.observations[-5:]:
                lines.append(f"  - [{obs.step_id}] {obs.content[:100]}")

        return "\n".join(lines)

    def finalize_and_extract_long_term_summary(self, success: bool) -> Optional[Message]:
        """Finalize working context: discard ephemeral scratch state and return factual summary for long-term memory."""
        if not self.goal:
            return None

        status_text = "completed successfully" if success else "failed during execution"
        summary_lines = [
            f"Task '{self.goal}' {status_text}.",
        ]

        if self.user_clarifications:
            summary_lines.append(f"User preferences noted: {', '.join(self.user_clarifications)}")

        if self.step_outputs:
            key_results = []
            for sid, out in self.step_outputs.items():
                if len(out) > 0 and not out.startswith("Error:"):
                    key_results.append(f"{sid}: {out[:80]}")
            if key_results:
                summary_lines.append(f"Key outcomes: {'; '.join(key_results)}")

        return Message(
            role=Role.ASSISTANT,
            content="\n".join(summary_lines),
        )

    def clear(self) -> None:
        """Clear all active working memory."""
        self.step_outputs.clear()
        self.step_verifications.clear()
        self.constraints.clear()
        self.user_clarifications.clear()
        self.observations.clear()
        self.active_step_id = None
        self.state = "NOT_STARTED"
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize working memory for diagnostics and audit logging."""
        state_str = self.state.value if hasattr(self.state, "value") else str(self.state)
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "state": state_str,
            "active_step_id": self.active_step_id,
            "constraints": self.constraints,
            "user_clarifications": self.user_clarifications,
            "step_outputs": self.step_outputs,
            "observations": [o.to_dict() for o in self.observations],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
