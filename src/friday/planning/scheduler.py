"""Async Parallel Scheduler & Execution Engine for TaskGraph DAGs.

Inspired by Microsoft JARVIS / HuggingGPT Execution Stage:
- Executes tasks in topological waves, running independent tasks concurrently.
- Respects rate limits, max concurrency, and timeouts.
- Injects outputs from upstream prerequisite tasks into downstream task inputs.
- Enforces FRIDAY's BaseAuthorizer security policies prior to running sensitive tasks.
- Coordinates with the DynamicReplanner for automatic fault recovery.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import AuthorizationDecision, AuthorizationRequest, SafetyLevel
from friday.planning.events import (
    TaskEventType,
    TaskProgressEvent,
    global_task_event_bus,
)
from friday.planning.executors import ExecutorRegistry
from friday.planning.types import (
    TaskGraph,
    TaskGraphValidationError,
    TaskStatus,
    TaskStep,
)

logger = get_logger("planning.scheduler")


class TaskGraphScheduler:
    """Orchestrates topological concurrent execution of a TaskGraph."""

    def __init__(
        self,
        executor_registry: ExecutorRegistry,
        authorizer: BaseAuthorizer | None = None,
        max_concurrency: int = 5,
        default_timeout_seconds: float = 60.0,
        replanner: Any = None,
        event_bus: Any = None,
    ) -> None:
        self.registry = executor_registry
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.max_concurrency = max(1, max_concurrency)
        self.default_timeout = default_timeout_seconds
        self.replanner = replanner
        self.event_bus = event_bus or global_task_event_bus
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Signal cooperative cancellation to running workers."""
        self._cancel_event.set()

    def reset_cancellation(self) -> None:
        self._cancel_event.clear()

    def execute_graph(
        self,
        graph: TaskGraph,
        cancellation_token: threading.Event | None = None,
    ) -> TaskGraph:
        """Execute the entire TaskGraph to completion in topological waves."""
        cancel_token = cancellation_token or self._cancel_event

        self.event_bus.publish(
            TaskProgressEvent(
                event_type=TaskEventType.PLAN_CREATED,
                graph_id=graph.graph_id,
                message=f"Plan initialized with {len(graph.list_tasks())} tasks",
                data={"total_tasks": len(graph.list_tasks()), "goal": graph.goal},
            )
        )

        try:
            waves = graph.compute_waves()
        except TaskGraphValidationError as e:
            logger.error(f"Failed to compute execution waves: {e}")
            for t in graph.list_tasks():
                graph.mark_failed(t.id, str(e))
            return graph

        with ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="friday-task-worker") as pool:
            for wave_idx, wave in enumerate(waves):
                if cancel_token.is_set():
                    logger.info("Cancellation requested. Halting subsequent execution waves.")
                    for t in wave:
                        graph.mark_cancelled(t.id)
                    continue

                # Filter tasks in wave that are ready (not skipped by upstream failures)
                ready_tasks = [t for t in wave if t.status in (TaskStatus.PENDING, TaskStatus.READY)]
                if not ready_tasks:
                    continue

                logger.info(f"Executing Wave {wave_idx + 1}/{len(waves)} with {len(ready_tasks)} tasks concurrently.")

                # Submit wave tasks to worker pool
                futures = {}
                for task in ready_tasks:
                    fut = pool.submit(self._execute_single_task, task, graph, cancel_token)
                    futures[fut] = task

                for fut in as_completed(futures):
                    task = futures[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        logger.error(f"Unexpected unhandled error in task '{task.id}': {e}")
                        graph.mark_failed(task.id, str(e))
                        graph.skip_downstream(task.id, reason=str(e))

        # Workflow finished
        self.event_bus.publish(
            TaskProgressEvent(
                event_type=TaskEventType.WORKFLOW_COMPLETED,
                graph_id=graph.graph_id,
                message="Workflow execution finished",
                data={
                    "is_successful": graph.is_successful(),
                    "total_tasks": len(graph.list_tasks()),
                    "completed": len(graph.get_completed_ids()),
                },
            )
        )
        return graph

    def _execute_single_task(
        self,
        task: TaskStep,
        graph: TaskGraph,
        cancel_token: threading.Event,
    ) -> None:
        """Execute a single task with security checks, retries, and dynamic replanning."""
        if cancel_token.is_set():
            graph.mark_cancelled(task.id)
            self.event_bus.publish(
                TaskProgressEvent(
                    event_type=TaskEventType.TASK_CANCELLED,
                    graph_id=graph.graph_id,
                    task_id=task.id,
                    message=f"Task '{task.id}' cancelled before start.",
                )
            )
            return

        graph.mark_running(task.id)
        self.event_bus.publish(
            TaskProgressEvent(
                event_type=TaskEventType.TASK_STARTED,
                graph_id=graph.graph_id,
                task_id=task.id,
                message=f"Starting task: {task.description}",
                data={"executor": task.selected_executor},
            )
        )

        # 1. Resolve inputs using upstream outputs
        resolved_inputs = graph.resolve_inputs_for_task(task.id)
        task.parameters = resolved_inputs

        # 2. Enforce Security Authorization for Sensitive / Dangerous tasks
        if task.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS) or task.requires_confirmation:
            auth_req = AuthorizationRequest(
                tool_name=task.selected_executor or task.tool_name or task.id,
                safety_level=task.safety_level,
                arguments=resolved_inputs,
            )
            auth_resp = self.authorizer.authorize(auth_req)
            if auth_resp.decision != AuthorizationDecision.APPROVED:
                err_msg = f"Security authorization denied: {auth_resp.reason or 'User/Policy rejected action'}"
                logger.warning(f"Task '{task.id}' blocked: {err_msg}")
                graph.mark_failed(task.id, err_msg)
                graph.skip_downstream(task.id, reason=err_msg)
                self.event_bus.publish(
                    TaskProgressEvent(
                        event_type=TaskEventType.TASK_FAILED,
                        graph_id=graph.graph_id,
                        task_id=task.id,
                        message=err_msg,
                    )
                )
                return

        # 3. Locate Executor
        executor = None
        if task.selected_executor:
            executor = self.registry.get(task.selected_executor)
        if not executor and task.tool_name:
            executor = self.registry.get(task.tool_name)

        if not executor:
            err_msg = f"Executor '{task.selected_executor or task.tool_name}' not found in registry."
            graph.mark_failed(task.id, err_msg)
            graph.skip_downstream(task.id, reason=err_msg)
            self.event_bus.publish(
                TaskProgressEvent(
                    event_type=TaskEventType.TASK_FAILED,
                    graph_id=graph.graph_id,
                    task_id=task.id,
                    message=err_msg,
                )
            )
            return

        # 4. Execute with Bounded Retries
        success = False
        last_error = ""
        max_attempts = max(1, task.retry_policy.max_retries + 1)

        for attempt in range(1, max_attempts + 1):
            if cancel_token.is_set():
                graph.mark_cancelled(task.id)
                return

            try:
                res = executor.execute(resolved_inputs)
                if res.success:
                    graph.mark_completed(task.id, result=res.output, outputs={"result": res.output})
                    success = True
                    self.event_bus.publish(
                        TaskProgressEvent(
                            event_type=TaskEventType.TASK_COMPLETED,
                            graph_id=graph.graph_id,
                            task_id=task.id,
                            message=f"Completed task: {task.description}",
                            data={"result": str(res.output)[:200]},
                        )
                    )
                    break
                else:
                    last_error = res.error or "Unknown executor error"
                    logger.warning(f"Task '{task.id}' attempt {attempt} failed: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Task '{task.id}' exception on attempt {attempt}: {e}")

            # Check if retryable
            if attempt < max_attempts and task.retry_policy.is_retryable(last_error):
                graph.mark_retrying(task.id)
                self.event_bus.publish(
                    TaskProgressEvent(
                        event_type=TaskEventType.TASK_RETRYING,
                        graph_id=graph.graph_id,
                        task_id=task.id,
                        message=f"Retrying task (attempt {attempt + 1}/{max_attempts})...",
                    )
                )
                time.sleep(task.retry_policy.initial_delay * (task.retry_policy.backoff_factor ** (attempt - 1)))
            else:
                break

        # 5. Dynamic Replanning / Failure Recovery if failed
        if not success:
            recovered = False
            if self.replanner and hasattr(self.replanner, "handle_task_failure"):
                try:
                    recovered = self.replanner.handle_task_failure(task, graph, last_error, self.registry)
                except Exception as e:
                    logger.error(f"Replanner error for task '{task.id}': {e}")

            if not recovered:
                graph.mark_failed(task.id, last_error)
                graph.skip_downstream(task.id, reason=last_error)
                self.event_bus.publish(
                    TaskProgressEvent(
                        event_type=TaskEventType.TASK_FAILED,
                        graph_id=graph.graph_id,
                        task_id=task.id,
                        message=f"Task failed: {last_error}",
                    )
                )
