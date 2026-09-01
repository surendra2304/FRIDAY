"""Proactive Memory System for FRIDAY.

Tracks operator commitments, deadlines, and unfinished interrupted workflows:
1. "User said they'd review the trading strategy tomorrow" -> Next day FRIDAY proactively asks:
   "You mentioned reviewing the trading strategy — want the current performance summary?"
2. Unfinished task tracking: "User started asking Forge to build something but got interrupted" ->
   Next session FRIDAY offers to resume.
3. Natural deadline and date parsing from ongoing conversations.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from friday.core.logging import get_logger

logger = get_logger("memory.proactive")


@dataclass
class UserCommitment:
    """User-stated commitment, intention, or future action."""
    commitment_id: str
    topic: str
    action_description: str
    target_date: datetime
    original_phrase: str
    status: str = "PENDING"  # PENDING, PROMPTED, FULFILLED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class UnfinishedTask:
    """An interrupted or partially configured workflow."""
    task_id: str
    subsystem: str  # forge, trading_bot, nexus, ai_universe
    task_description: str
    interrupted_stage: str
    status: str = "INTERRUPTED"  # INTERRUPTED, RESUMED, DISCARDED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ProactiveMemory:
    """Manages proactive reminders for user commitments, deadlines, and unfinished tasks."""

    def __init__(self) -> None:
        self.commitments: list[UserCommitment] = []
        self.unfinished_tasks: list[UnfinishedTask] = []
        self._lock = threading.RLock()

    def record_commitment(
        self,
        topic: str,
        action_description: str,
        target_date: datetime,
        original_phrase: str,
    ) -> UserCommitment:
        """Records a user commitment or future promise."""
        with self._lock:
            cid = f"commit_{int(datetime.now(timezone.utc).timestamp())}_{len(self.commitments)}"
            commitment = UserCommitment(
                commitment_id=cid,
                topic=topic,
                action_description=action_description,
                target_date=target_date,
                original_phrase=original_phrase,
            )
            self.commitments.append(commitment)
            logger.info(f"[PROACTIVE_MEMORY] Recorded user commitment for {target_date.isoformat()}: {topic}")
            return commitment

    def extract_commitment_from_text(self, text: str) -> UserCommitment | None:
        """Extracts commitments (e.g. 'I will review the strategy tomorrow')."""
        clean = text.lower()
        now = datetime.now(timezone.utc)

        if "review" in clean and ("tomorrow" in clean or "next day" in clean):
            target = now + timedelta(days=1)
            topic = "trading strategy" if "trading" in clean or "strategy" in clean else "system performance"
            return self.record_commitment(
                topic=topic,
                action_description=f"Review {topic}",
                target_date=target,
                original_phrase=text,
            )

        if "check" in clean and "tomorrow" in clean:
            target = now + timedelta(days=1)
            topic = "website leads" if "leads" in clean or "website" in clean else "open positions"
            return self.record_commitment(
                topic=topic,
                action_description=f"Check {topic}",
                target_date=target,
                original_phrase=text,
            )

        return None

    def check_pending_commitments(self, current_time: datetime | None = None) -> list[str]:
        """Returns proactive spoken prompts for commitments whose target date has arrived."""
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            prompts: list[str] = []

            for com in self.commitments:
                if com.status == "PENDING" and now >= com.target_date:
                    com.status = "PROMPTED"
                    if "trading" in com.topic or "strategy" in com.topic:
                        prompts.append("You mentioned reviewing the trading strategy — want the current performance summary?")
                    elif "lead" in com.topic or "website" in com.topic:
                        prompts.append("You mentioned checking the website leads — want the latest lead summary?")
                    else:
                        prompts.append(f"You mentioned that you would {com.action_description.lower()} — would you like to review that now?")

            return prompts

    def record_unfinished_task(
        self,
        subsystem: str,
        task_description: str,
        interrupted_stage: str,
    ) -> UnfinishedTask:
        """Records an interrupted or paused workflow."""
        with self._lock:
            tid = f"task_unf_{int(datetime.now(timezone.utc).timestamp())}_{len(self.unfinished_tasks)}"
            task = UnfinishedTask(
                task_id=tid,
                subsystem=subsystem,
                task_description=task_description,
                interrupted_stage=interrupted_stage,
            )
            self.unfinished_tasks.append(task)
            logger.info(f"[PROACTIVE_MEMORY] Recorded unfinished {subsystem} task: {task_description}")
            return task

    def check_unfinished_tasks(self) -> list[str]:
        """Returns proactive resumption prompts for interrupted tasks."""
        with self._lock:
            prompts: list[str] = []
            for t in self.unfinished_tasks:
                if t.status == "INTERRUPTED":
                    t.status = "PROMPTED"
                    if t.subsystem == "forge":
                        prompts.append(f"You started asking Forge to build '{t.task_description}' earlier — want to resume where you left off?")
                    elif t.subsystem == "nexus":
                        prompts.append(f"You were configuring a Nexus workflow for '{t.task_description}' — would you like to complete it?")
                    else:
                        prompts.append(f"You have an unfinished {t.subsystem} task ({t.task_description}) — want to resume?")
            return prompts


# Default singleton instance
proactive_memory = ProactiveMemory()
