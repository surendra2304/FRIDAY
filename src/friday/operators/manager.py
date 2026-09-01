"""Operator Manager for managing, ticking, and dispatching Persistent Operators."""

import asyncio
import threading

from friday.core.logging import get_logger
from friday.operators.base_operator import BaseOperator, OperatorExecutionResult

logger = get_logger("operators.manager")


class OperatorManager:
    """Central registry and execution coordinator for persistent operators."""

    def __init__(self) -> None:
        self._operators: dict[str, BaseOperator] = {}
        self._lock = threading.RLock()

    def register_operator(self, operator: BaseOperator) -> None:
        """Register an operator and start it."""
        with self._lock:
            self._operators[operator.operator_id] = operator
            operator.start()
            logger.info(f"Registered and started operator '{operator.name}' ({operator.operator_id})")

    def unregister_operator(self, operator_id: str) -> bool:
        """Stop and remove an operator by ID or name."""
        with self._lock:
            op = self._operators.get(operator_id)
            if not op:
                # Look up by name
                for k, v in list(self._operators.items()):
                    if v.name == operator_id:
                        op = v
                        operator_id = k
                        break
            if op:
                op.stop()
                del self._operators[operator_id]
                logger.info(f"Unregistered operator '{op.name}' ({operator_id})")
                return True
        return False

    def get_operator(self, operator_id: str) -> BaseOperator | None:
        with self._lock:
            op = self._operators.get(operator_id)
            if not op:
                for v in self._operators.values():
                    if v.name == operator_id:
                        return v
            return op

    def list_operators(self) -> list[BaseOperator]:
        with self._lock:
            return list(self._operators.values())

    def start_all(self) -> None:
        with self._lock:
            for op in self._operators.values():
                op.start()

    def stop_all(self) -> None:
        with self._lock:
            for op in self._operators.values():
                op.stop()

    def tick_all(self) -> list[OperatorExecutionResult]:
        """Evaluate triggers for all registered operators and dispatch events."""
        results: list[OperatorExecutionResult] = []
        with self._lock:
            ops_to_tick = list(self._operators.values())

        for op in ops_to_tick:
            try:
                event = op.evaluate_triggers()
                if event is not None:
                    res = op.handle_event(event)
                    results.append(res)
            except Exception as e:
                logger.error(f"Error ticking operator '{op.name}': {e}", exc_info=True)

        return results

    async def run_loop(self, tick_interval: float = 1.0, stop_event: asyncio.Event | None = None) -> None:
        """Run operator trigger polling loop as an asyncio background task."""
        logger.info(f"Started OperatorManager async background loop (interval: {tick_interval}s)")
        while stop_event is None or not stop_event.is_set():
            self.tick_all()
            await asyncio.sleep(tick_interval)


# Default process-level operator manager singleton
operator_manager = OperatorManager()
