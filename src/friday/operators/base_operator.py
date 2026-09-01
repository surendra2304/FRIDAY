"""Base Operator Abstraction for Persistent Background State Machines (Inspired by OpenJarvis).

An Operator is a persistent background state machine that monitors system state over time
and autonomously triggers actions, skill executions, or notifications based on event-driven triggers.
"""

import threading
import uuid
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import AuthorizationDecision, AuthorizationRequest, SafetyLevel

logger = get_logger("operators.base")


class OperatorState(str, Enum):
    """Lifecycle states of a persistent operator."""
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    TRIGGERED = "TRIGGERED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class OperatorExecutionResult:
    """Result of an operator execution cycle."""
    operator_id: str
    operator_name: str
    success: bool
    output: Any
    triggered_by: str | None = None
    event_data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "operator_name": self.operator_name,
            "success": self.success,
            "output": str(self.output),
            "triggered_by": self.triggered_by,
            "event_data": self.event_data,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseOperator(ABC):
    """Abstract Base Class for persistent, event-driven operators."""

    def __init__(
        self,
        name: str,
        description: str = "",
        operator_id: str | None = None,
        safety_level: SafetyLevel = SafetyLevel.SAFE,
        triggers: list[Any] | None = None,
        target_skill_name: str | None = None,
        target_action: Callable[[dict[str, Any]], Any] | None = None,
        notification_category: str | None = None,
        authorizer: BaseAuthorizer | None = None,
        notification_manager: Any | None = None,
        skill_registry: Any | None = None,
    ) -> None:
        self.operator_id = operator_id or f"op_{uuid.uuid4().hex[:10]}"
        self.name = name
        self.description = description
        self.safety_level = safety_level
        self.triggers: list[Any] = list(triggers or [])
        self.target_skill_name = target_skill_name
        self.target_action = target_action
        self.notification_category = notification_category or "operator_event"
        self.authorizer: BaseAuthorizer = authorizer or DefaultSecureAuthorizer()
        self.notification_manager = notification_manager
        self.skill_registry = skill_registry
        self.downstream_operators: list[BaseOperator] = []

        self._state: OperatorState = OperatorState.INITIALIZED
        self._lock = threading.RLock()
        self.last_event: dict[str, Any] | None = None
        self.last_result: OperatorExecutionResult | None = None
        self.run_count: int = 0

    @property
    def state(self) -> OperatorState:
        with self._lock:
            return self._state

    def check_state(self) -> OperatorState:
        """Query the current state of the operator."""
        return self.state

    def start(self) -> None:
        """Activate the operator and all its triggers."""
        with self._lock:
            if self._state == OperatorState.RUNNING:
                return
            for t in self.triggers:
                t.start()
            self._state = OperatorState.RUNNING
            logger.info(f"Operator '{self.name}' ({self.operator_id}) started.")

    def stop(self) -> None:
        """Deactivate the operator and all its triggers."""
        with self._lock:
            for t in self.triggers:
                t.stop()
            self._state = OperatorState.STOPPED
            logger.info(f"Operator '{self.name}' ({self.operator_id}) stopped.")

    def pause(self) -> None:
        """Pause trigger evaluation."""
        with self._lock:
            if self._state == OperatorState.RUNNING:
                self._state = OperatorState.PAUSED
                logger.info(f"Operator '{self.name}' paused.")

    def resume(self) -> None:
        """Resume trigger evaluation from paused state."""
        with self._lock:
            if self._state == OperatorState.PAUSED:
                self._state = OperatorState.RUNNING
                logger.info(f"Operator '{self.name}' resumed.")

    def add_trigger(self, trigger: Any) -> None:
        """Add a trigger to this operator."""
        with self._lock:
            self.triggers.append(trigger)
            if self._state == OperatorState.RUNNING:
                trigger.start()

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger by ID."""
        with self._lock:
            for i, t in enumerate(self.triggers):
                if getattr(t, "trigger_id", "") == trigger_id or getattr(t, "name", "") == trigger_id:
                    t.stop()
                    self.triggers.pop(i)
                    return True
        return False

    def pipe_to(self, downstream_operator: "BaseOperator") -> "BaseOperator":
        """Chain this operator's output into another operator's execution."""
        with self._lock:
            if downstream_operator not in self.downstream_operators:
                self.downstream_operators.append(downstream_operator)
        return downstream_operator

    def __or__(self, downstream_operator: "BaseOperator") -> "BaseOperator":
        """Operator chaining pipeline syntax: op1 | op2."""
        return self.pipe_to(downstream_operator)

    def evaluate_triggers(self) -> dict[str, Any] | None:
        """Check all registered triggers. Returns event data if any trigger fired."""
        with self._lock:
            if self._state != OperatorState.RUNNING:
                return None

            for trigger in self.triggers:
                event = trigger.evaluate()
                if event is not None:
                    event["trigger_name"] = getattr(trigger, "name", "unknown")
                    event["trigger_id"] = getattr(trigger, "trigger_id", "")
                    return event
        return None

    def handle_event(self, event_data: dict[str, Any]) -> OperatorExecutionResult:
        """Process a detected event with safety checks, action execution, and chaining."""
        with self._lock:
            self._state = OperatorState.TRIGGERED
            self.last_event = event_data
            self.run_count += 1

            trigger_name = event_data.get("trigger_name", "manual")
            logger.info(f"Operator '{self.name}' triggered by '{trigger_name}': {event_data}")

            # 1. Authorizer Safety Boundary Check
            auth_req = AuthorizationRequest(
                tool_name=f"operator:{self.name}",
                safety_level=self.safety_level,
                arguments={"event": event_data, "operator_id": self.operator_id},
                purpose=f"Execute persistent operator '{self.name}'",
            )
            auth_res = self.authorizer.authorize(auth_req)
            if auth_res.decision != AuthorizationDecision.APPROVED:
                err_msg = f"Safety Block: Operator '{self.name}' execution blocked by authorizer: {auth_res.reason}"
                logger.warning(err_msg)
                self._state = OperatorState.ERROR
                res = OperatorExecutionResult(
                    operator_id=self.operator_id,
                    operator_name=self.name,
                    success=False,
                    output=None,
                    triggered_by=trigger_name,
                    event_data=event_data,
                    error=err_msg,
                )
                self.last_result = res
                return res

            # 2. Execute Action / Skill / Notification
            output = None
            success = True
            error_msg = None

            try:
                # Target Action Callback
                if self.target_action:
                    output = self.target_action(event_data)
                else:
                    output = self.execute_action(event_data)

                # Skill Execution (if configured)
                if self.target_skill_name and self.skill_registry:
                    skill = self.skill_registry.get(self.target_skill_name)
                    if skill:
                        # Authorize skill capabilities
                        is_auth, reason = self.authorizer.authorize_skill(skill)
                        if is_auth:
                            skill_res = skill.execute(user_request=f"Operator event: {event_data}")
                            output = {"action_output": output, "skill_output": skill_res.output}
                        else:
                            logger.warning(f"Operator skill execution blocked: {reason}")
                            output = {"action_output": output, "skill_blocked": reason}

                # Notification Post (if manager configured)
                if self.notification_manager and output is not None:
                    try:
                        self.notification_manager.post_notification(
                            message=f"Operator [{self.name}]: {str(output)[:200]}",
                            category=self.notification_category,
                            severity="info",
                            metadata={"event": event_data, "operator_id": self.operator_id},
                        )
                    except Exception as n_err:
                        logger.debug(f"Notification error: {n_err}")

            except Exception as e:
                logger.exception(f"Error executing operator '{self.name}': {e}")
                success = False
                error_msg = str(e)
                self._state = OperatorState.ERROR

            res = OperatorExecutionResult(
                operator_id=self.operator_id,
                operator_name=self.name,
                success=success,
                output=output,
                triggered_by=trigger_name,
                event_data=event_data,
                error=error_msg,
            )
            self.last_result = res

            # 3. Propagate to downstream chained operators
            if success and self.downstream_operators:
                chained_event = {
                    "event_type": "operator_chained_output",
                    "upstream_operator": self.name,
                    "upstream_output": output,
                    "parent_event": event_data,
                }
                for downstream in self.downstream_operators:
                    logger.info(f"Chaining output from '{self.name}' -> '{downstream.name}'")
                    downstream.handle_event(chained_event)

            if self._state == OperatorState.TRIGGERED:
                self._state = OperatorState.RUNNING

            return res

    def execute_action(self, event_data: dict[str, Any]) -> Any:
        """Default action handler to be overridden by subclasses if target_action is not passed."""
        return f"Processed event: {event_data.get('event_type', 'generic')}"
