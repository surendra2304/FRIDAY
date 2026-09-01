import threading
import time
from datetime import datetime, timedelta, timezone

from friday.agent.agent import FridayAgent
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import AuthorizationRequest
from friday.core.types import SafetyLevel as CoreSafetyLevel

from .models import SafetyLevel, ScheduleType, Task, TaskRunLog
from .sqlite_store import get_all_tasks, log_task_run, save_task

logger = get_logger("tasks.scheduler")

class TaskScheduler:
    """Background scheduler for proactive tasks.
    Checks SQLite task table each second and runs due tasks.
    """

    def __init__(self, agent: FridayAgent):
        self.agent = agent
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self.settings = get_settings()
        self.authorizer = DefaultSecureAuthorizer()

    def start(self) -> None:
        self._thread.start()
        logger.info("TaskScheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join()
        logger.info("TaskScheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_due_tasks()
            except Exception as e:
                logger.error(f"TaskScheduler loop error: {e}")
            time.sleep(1)

    def _process_due_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        tasks = get_all_tasks()
        for task in tasks:
            if not task.enabled:
                continue
            if task.daily_cap is not None and task.run_count >= task.daily_cap:
                continue
            if task.max_calls is not None and task.run_count >= task.max_calls:
                task.enabled = False
                save_task(task)
                continue
            if self._is_task_due(task, now):
                self._run_task(task)

    def _is_task_due(self, task: Task, now: datetime) -> bool:
        st = task.schedule_type
        params = task.schedule_params
        lr = (task.last_run if task.last_run.tzinfo else task.last_run.replace(tzinfo=timezone.utc)) if task.last_run else None
        if st == ScheduleType.ONE_TIME:
            run_at = datetime.fromisoformat(params["run_at"])
            run_at = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
            return now >= run_at and (lr is None or lr < run_at)
        if st == ScheduleType.INTERVAL:
            interval = int(params.get("interval_seconds", 60))
            if lr is None:
                return True
            return now >= lr + timedelta(seconds=interval)
        if st == ScheduleType.DAILY:
            hour = int(params.get("hour", 0))
            minute = int(params.get("minute", 0))
            today_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return now >= today_run and (lr is None or lr < today_run)
        if st == ScheduleType.WEEKLY:
            weekday = int(params.get("weekday", 0))  # 0=Monday
            hour = int(params.get("hour", 0))
            minute = int(params.get("minute", 0))
            days_ago = (now.weekday() - weekday) % 7
            target_day = now - timedelta(days=days_ago)
            target_dt = target_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return now >= target_dt and (lr is None or lr < target_dt)
        return False

    def _run_task(self, task: Task) -> None:
        logger.info(f"Executing task: {task.name} ({task.id})")
        auth_req = AuthorizationRequest(
            tool_name="scheduler_run_task",
            parameters={"task_id": task.id, "prompt": task.prompt},
            safety_level=CoreSafetyLevel.LOW,
        )
        authorizer = DefaultSecureAuthorizer()
        auth_res = authorizer.authorize(auth_req)
        if not auth_res.approved:
            logger.warning(f"Task {task.name} blocked by authorizer: {auth_res.reason}")
            return

        success = False
        result = None
        error_msg = None
        attempt = 0
        while attempt < self.settings.gemini_max_retries and not success:
            attempt += 1
            try:
                response = self.agent.process_message(task.prompt)
                success = True
                result = getattr(response, "content", str(response))
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Task {task.name} attempt {attempt} failed: {e}")

        # Update counters
        task.run_count += 1
        if success:
            task.failure_streak = 0
        else:
            task.failure_streak += 1
            if task.failure_streak >= self.settings.task_circuit_breaker_threshold:
                task.enabled = False
                logger.error(f"Task {task.name} disabled by circuit breaker")
        task.last_run = datetime.now(timezone.utc)
        save_task(task)

        # Log execution
        log = TaskRunLog(
            task_id=task.id,
            success=success,
            result=result,
            error=error_msg,
            attempt=attempt,
        )
        log_task_run(log)

        # Notification
        msg = f"Task '{task.name}' completed: {'success' if success else 'failure'}"
        logger.info(msg)
