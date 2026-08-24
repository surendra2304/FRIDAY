# -*- coding: utf-8 -*-
"""Workflow Scheduler for FRIDAY Phase 17 Proactive System.

Executes periodic (interval/cron-like) and condition-based background workflows.
"""

import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, AuthorizationRequest, AuthorizationDecision
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer

logger = get_logger("workflows.scheduler")


@dataclass
class ScheduledJob:
    """Represents a scheduled periodic or conditional task."""

    job_id: str
    name: str
    action_fn: Callable[[], Any]
    interval_seconds: Optional[float] = None
    file_watch_path: Optional[str] = None
    safety_level: SafetyLevel = SafetyLevel.SAFE
    last_run: Optional[datetime] = None
    last_file_mtime: Optional[float] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkflowScheduler:
    """Manages scheduled background workflows with bounded execution safety."""

    def __init__(
        self,
        authorizer: Optional[BaseAuthorizer] = None,
        tick_interval: float = 1.0,
        notification_manager: Optional[Any] = None,
    ) -> None:
        self.authorizer: BaseAuthorizer = authorizer or DefaultSecureAuthorizer()
        self.tick_interval = tick_interval
        self.notification_manager = notification_manager
        self._jobs: Dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Tracking for high CPU sustained spikes (Phase 25)
        self._high_cpu_start_time: Optional[float] = None
        self._last_alerted_cpu_time: float = 0.0

    def check_system_resources_proactive(self, cpu_threshold: float = 90.0, sustained_seconds: float = 120.0) -> Optional[Dict[str, Any]]:
        """Check for sustained high CPU utilization and queue proactive alerts."""
        try:
            from friday.tools.builtin.system_monitor import get_current_system_resources
            stats = get_current_system_resources()
            cpu = stats.get("cpu_percent", 0.0)
            now = time.time()

            if cpu >= cpu_threshold:
                if self._high_cpu_start_time is None:
                    self._high_cpu_start_time = now
                elif (now - self._high_cpu_start_time) >= sustained_seconds:
                    if (now - self._last_alerted_cpu_time) > 300.0:  # alert at most every 5m
                        top_proc = stats.get("top_processes", [{}])[0].get("name", "an application")
                        msg = f"I noticed your CPU is maxed out at {cpu}% by {top_proc}. Would you like me to close it?"
                        if self.notification_manager is not None:
                            self.notification_manager.post_notification(
                                message=msg,
                                category="system_health",
                                severity="warning",
                                metadata={"cpu_percent": cpu, "process": top_proc},
                            )
                        self._last_alerted_cpu_time = now
                        return {"alert": True, "message": msg, "cpu": cpu, "process": top_proc}
            else:
                self._high_cpu_start_time = None
            return {"alert": False, "cpu": cpu}
        except Exception as e:
            logger.debug(f"Proactive system resource check error: {e}")
            return None

    def register_interval_job(
        self,
        name: str,
        interval_seconds: float,
        action_fn: Callable[[], Any],
        safety_level: SafetyLevel = SafetyLevel.SAFE,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a time-based recurring job (e.g., every N seconds/minutes)."""
        job_id = str(uuid.uuid4())
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            action_fn=action_fn,
            interval_seconds=interval_seconds,
            safety_level=safety_level,
            metadata=metadata or {},
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info(f"Registered interval job '{name}' (ID: {job_id}, Interval: {interval_seconds}s)")
        return job_id

    def register_file_watch_job(
        self,
        name: str,
        file_path: str,
        action_fn: Callable[[], Any],
        safety_level: SafetyLevel = SafetyLevel.SAFE,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a condition-based job triggered when a file is modified."""
        job_id = str(uuid.uuid4())
        initial_mtime = os.path.getmtime(file_path) if os.path.exists(file_path) else None
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            action_fn=action_fn,
            file_watch_path=file_path,
            last_file_mtime=initial_mtime,
            safety_level=safety_level,
            metadata=metadata or {},
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info(f"Registered file watch job '{name}' (ID: {job_id}, Path: {file_path})")
        return job_id

    def unregister_job(self, job_id: str) -> bool:
        """Remove a job by ID."""
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
        return False

    def list_jobs(self) -> List[ScheduledJob]:
        """Return list of all registered jobs."""
        with self._lock:
            return list(self._jobs.values())

    def start(self) -> None:
        """Start the background scheduler loop."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run_loop,
            name="WorkflowSchedulerThread",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Started WorkflowScheduler daemon thread.")

    def stop(self) -> None:
        """Stop scheduler and wait for background thread to exit."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        logger.info("Stopped WorkflowScheduler.")

    def run_pending_jobs_once(self, force_interval: bool = False) -> int:
        """Check all registered jobs and trigger due ones immediately (useful for testing/deterministic ticks)."""
        now = datetime.now(timezone.utc)
        executed_count = 0

        with self._lock:
            jobs_to_eval = list(self._jobs.values())

        for job in jobs_to_eval:
            if not job.is_active:
                continue

            should_execute = False
            # 1. Interval Check
            if job.interval_seconds is not None:
                if job.last_run is None or force_interval:
                    should_execute = True
                else:
                    elapsed = (now - job.last_run).total_seconds()
                    if elapsed >= job.interval_seconds:
                        should_execute = True

            # 2. File Watch Condition Check
            if job.file_watch_path and os.path.exists(job.file_watch_path):
                current_mtime = os.path.getmtime(job.file_watch_path)
                if job.last_file_mtime is None or current_mtime > job.last_file_mtime:
                    should_execute = True
                    job.last_file_mtime = current_mtime

            if should_execute:
                # Authorizer safety check
                auth_req = AuthorizationRequest(
                    tool_name=job.name,
                    safety_level=job.safety_level,
                    arguments={"job_id": job.job_id},
                    purpose=f"Execute scheduled job '{job.name}'",
                )
                auth_res = self.authorizer.authorize(auth_req)
                if auth_res.decision != AuthorizationDecision.APPROVED:
                    logger.warning(
                        f"Blocked scheduled job '{job.name}' execution: {auth_res.reason}"
                    )
                    continue

                try:
                    job.last_run = now
                    job.action_fn()
                    executed_count += 1
                    logger.info(f"Executed scheduled job '{job.name}' successfully.")
                except Exception as e:
                    logger.error(f"Error running scheduled job '{job.name}': {e}", exc_info=True)

        return executed_count

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_pending_jobs_once()
            except Exception as e:
                logger.error(f"Error in scheduler loop tick: {e}", exc_info=True)
            self._stop_event.wait(self.tick_interval)
