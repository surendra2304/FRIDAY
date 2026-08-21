import threading
import time
from datetime import datetime, timedelta

from .models import Task, ScheduleType, SafetyLevel
from .sqlite_store import get_all_tasks, save_task, log_task_run
from friday.core.config import get_settings
from friday.agent.agent import FridayAgent
from friday.core.auth import DefaultSecureAuthorizer

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
        self.agent.logger.info("TaskScheduler started")

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join()
        self.agent.logger.info("TaskScheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process_due_tasks()
            except Exception as e:
                self.agent.logger.error(f"TaskScheduler loop error: {e}")
            time.sleep(1)

    def _process_due_tasks(self) -> None:
        now = datetime.utcnow()
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
        if st == ScheduleType.ONE_TIME:
            run_at = datetime.fromisoformat(params["run_at"])
            return now >= run_at and (task.last_run is None or task.last_run < run_at)
        if st == ScheduleType.INTERVAL:
            interval = int(params.get("interval_seconds", 60))
            if task.last_run is None:
                return True
            return now >= task.last_run + timedelta(seconds=interval)
        if st == ScheduleType.DAILY:
            hour = int(params.get("hour", 0))
            minute = int(params.get("minute", 0))
            today_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return now >= today_run and (task.last_run is None or task.last_run < today_run)
        if st == ScheduleType.WEEKLY:
            weekday = int(params.get("weekday", 0))  # 0=Monday
            hour = int(params.get("hour", 0))
            minute = int(params.get("minute", 0))
            days_ago = (now.weekday() - weekday) % 7
            target_day = now - timedelta(days=days_ago)
            target_dt = target_day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return now >= target_dt and (task.last_run is None or task.last_run < target_dt)
        return False

    def _run_task(self, task: Task) -> None:
        # Authorization based on safety level
        if task.safety_level == SafetyLevel.SAFE:
            authorized = True
        elif task.safety_level == SafetyLevel.SENSITIVE:
            authorized = self.authorizer.authorize_sensitive(task.name)
        else:  # DANGEROUS
            authorized = self.authorizer.authorize_dangerous(task.name, require_confirmation=True)

        if not authorized:
            self.agent.logger.warning(f"Task {task.name} not authorized, skipping")
            return

        attempt = 0
        success = False
        result = None
        error_msg = None
        while attempt < task.retry_limit and not success:
            attempt += 1
            try:
                # Example execution: send a simple command to the agent
                response = self.agent.process_message(f"/run_task {task.name}")
                success = True
                result = getattr(response, "content", str(response))
            except Exception as e:
                error_msg = str(e)
                self.agent.logger.error(f"Task {task.name} attempt {attempt} failed: {e}")
                time.sleep(self.settings.gemini_backoff_factor ** attempt)

        # Update counters
        task.run_count += 1
        if success:
            task.failure_streak = 0
        else:
            task.failure_streak += 1
            if task.failure_streak >= self.settings.task_circuit_breaker_threshold:
                task.enabled = False
                self.agent.logger.error(f"Task {task.name} disabled by circuit breaker")
        task.last_run = datetime.utcnow()
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
        self.agent.logger.info(msg)
        if self.settings.voice_enabled:
            try:
                from friday.voice.session import VoiceSession
                from friday.voice.gemini_provider import GeminiVoiceProvider
                provider = GeminiVoiceProvider()
                vs = VoiceSession(provider, self.agent)
                vs.speak(msg)
            except Exception:
                pass
