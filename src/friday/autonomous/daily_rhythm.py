"""Daily Rhythm & Goal Accountability Manager for FRIDAY.

Provides:

- Daily focus objectives, morning intention planning, and evening reflection.
- Persistence into the ``FRIDAY`` Oracle schema (``daily_goals``) through
  :mod:`friday.core.oracle`.
- A test-only SQLite path for isolated unit tests. Production never creates a
  local goals database.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from friday.core import oracle
from friday.core.exceptions import PersistenceConfigError
from friday.core.logging import get_logger
from friday.core.oracle import ephemeral_backend_allowed

logger = get_logger("autonomous.daily_rhythm")

_GOAL_COLUMNS = (
    "id, goal_date, title, description, status, progress, created_at, updated_at, notes"
)


def get_oracle_dsn() -> str | None:
    """Resolve the Oracle Autonomous Database DSN, or None when unset.

    Every accepted Oracle URL form is normalised to ``oracle+oracledb://`` so
    SQLAlchemy's single Oracle dialect serves both sync and async engines.
    """
    raw_url = (
        os.getenv("ORACLE_CORE_ASYNC_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("FRIDAY_DATABASE_URL")
    )
    if not raw_url:
        return None
    return oracle.normalise_oracle_url(raw_url)


@dataclass(frozen=True)
class DailyGoal:
    id: int
    goal_date: str  # YYYY-MM-DD
    title: str
    description: str
    status: str  # "pending", "in_progress", "completed", "deferred"
    progress: float  # 0.0 to 1.0
    created_at: str
    updated_at: str
    notes: str = ""


class DailyRhythmManager:
    """Manages daily focus objectives, morning briefings, and evening check-ins.

    Persists into Oracle Autonomous Database (``FRIDAY.daily_goals``). An
    explicit ``db_path`` selects a test-only SQLite file and is rejected outside
    a pytest run.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        dsn: Optional[str] = None,
    ) -> None:
        self.db_path = db_path
        self._dsn = dsn
        self._backend = "oracle"
        if db_path:
            if not ephemeral_backend_allowed():
                raise PersistenceConfigError(
                    "DailyRhythmManager(db_path=...) is test-only; omit db_path so "
                    "goals are written to Oracle Autonomous Database."
                )
            self._backend = "sqlite"
            self._init_sqlite()

        # Surendra's Operating Rhythm: Awake 09:00 AM to 00:00 Midnight
        self.wake_hour: int = 9
        self.sleep_hour: int = 0
        self.user_name: str = "Surendra"

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_date TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'in_progress',
                    progress REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notes TEXT DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_date ON daily_goals(goal_date)")
            conn.commit()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _set_goal(self, dt: str, title: str, description: str, now_iso: str) -> int:
        if self._backend == "sqlite":
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM daily_goals WHERE goal_date = ? ORDER BY id DESC LIMIT 1",
                    (dt,),
                )
                row = cursor.fetchone()
                if row:
                    gid = row[0]
                    cursor.execute(
                        "UPDATE daily_goals SET title = ?, description = ?, updated_at = ?, "
                        "status = 'in_progress' WHERE id = ?",
                        (title, description, now_iso, gid),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO daily_goals "
                        "(goal_date, title, description, status, progress, created_at, updated_at, notes) "
                        "VALUES (?, ?, ?, 'in_progress', 0.0, ?, ?, '')",
                        (dt, title, description, now_iso, now_iso),
                    )
                    gid = cursor.lastrowid
                conn.commit()
                return int(gid)

        row = oracle.query_one(
            "SELECT id FROM daily_goals WHERE goal_date = :dt "
            "ORDER BY id DESC FETCH FIRST 1 ROWS ONLY",
            {"dt": dt},
        )
        if row:
            oracle.execute(
                "UPDATE daily_goals SET title = :title, description = :description, "
                "updated_at = :updated_at, status = 'in_progress' WHERE id = :id",
                {
                    "title": title,
                    "description": oracle.nullif_empty(description),
                    "updated_at": now_iso,
                    "id": row["id"],
                },
            )
            return int(row["id"])
        oracle.execute(
            "INSERT INTO daily_goals "
            "(goal_date, title, description, status, progress, created_at, updated_at, notes) "
            "VALUES (:dt, :title, :description, 'in_progress', 0.0, :created_at, :updated_at, NULL)",
            {
                "dt": dt,
                "title": title,
                "description": oracle.nullif_empty(description),
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        created = oracle.query_one(
            "SELECT id FROM daily_goals WHERE goal_date = :dt "
            "ORDER BY id DESC FETCH FIRST 1 ROWS ONLY",
            {"dt": dt},
        )
        return int(created["id"]) if created else 0

    def _update_goal(
        self, gid: int, progress: float, status: str, notes: str, now_iso: str
    ) -> None:
        if self._backend == "sqlite":
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE daily_goals SET progress = ?, status = ?, notes = ?, "
                    "updated_at = ? WHERE id = ?",
                    (progress, status, notes, now_iso, gid),
                )
                conn.commit()
            return
        oracle.execute(
            "UPDATE daily_goals SET progress = :progress, status = :status, "
            "notes = :notes, updated_at = :updated_at WHERE id = :id",
            {
                "progress": progress,
                "status": status,
                "notes": oracle.nullif_empty(notes),
                "updated_at": now_iso,
                "id": gid,
            },
        )

    async def set_daily_goal_async(
        self,
        title: str,
        description: str = "",
        target_date: Optional[str] = None,
    ) -> DailyGoal:
        """Set the primary focus goal for today (or target date) asynchronously."""
        dt = target_date or self._today()
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_title = title.strip()
        await asyncio.to_thread(self._set_goal, dt, clean_title, description, now_iso)
        goal = await self.get_active_goal_async(dt)
        if goal is None:
            raise PersistenceConfigError("Daily goal was written but could not be read back")
        return goal

    def set_daily_goal(
        self,
        title: str,
        description: str = "",
        target_date: Optional[str] = None,
    ) -> DailyGoal:
        """Set the primary focus goal for today (or target date)."""
        dt = target_date or self._today()
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_title = title.strip()
        self._set_goal(dt, clean_title, description, now_iso)
        goal = self.get_active_goal(dt)
        if goal is None:
            raise PersistenceConfigError("Daily goal was written but could not be read back")
        logger.info("Set daily goal for %s: %s", dt, clean_title)
        return goal

    async def get_active_goal_async(self, target_date: Optional[str] = None) -> Optional[DailyGoal]:
        """Get the active goal for today (or specified date) asynchronously."""
        return await asyncio.to_thread(self.get_active_goal, target_date)

    def get_active_goal(self, target_date: Optional[str] = None) -> Optional[DailyGoal]:
        """Get the active goal for today (or specified date)."""
        dt = target_date or self._today()
        if self._backend == "sqlite":
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT {_GOAL_COLUMNS} FROM daily_goals WHERE goal_date = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (dt,),
                )
                row = cursor.fetchone()
                if row:
                    return DailyGoal(
                        id=row[0],
                        goal_date=row[1],
                        title=row[2],
                        description=row[3],
                        status=row[4],
                        progress=row[5],
                        created_at=row[6],
                        updated_at=row[7],
                        notes=row[8],
                    )
            return None

        row = oracle.query_one(
            f"SELECT {_GOAL_COLUMNS} FROM daily_goals WHERE goal_date = :dt "
            "ORDER BY id DESC FETCH FIRST 1 ROWS ONLY",
            {"dt": dt},
        )
        if not row:
            return None
        return DailyGoal(
            id=int(row["id"]),
            goal_date=row["goal_date"],
            title=row["title"],
            description=row["description"] or "",
            status=row["status"] or "in_progress",
            progress=float(row["progress"] or 0.0),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            notes=row["notes"] or "",
        )

    async def update_goal_progress_async(
        self,
        progress: float,
        status: Optional[str] = None,
        notes: str = "",
        target_date: Optional[str] = None,
    ) -> Optional[DailyGoal]:
        """Update progress (0.0 to 1.0) and optional status asynchronously."""
        return await asyncio.to_thread(
            self.update_goal_progress, progress, status, notes, target_date
        )

    def update_goal_progress(
        self,
        progress: float,
        status: Optional[str] = None,
        notes: str = "",
        target_date: Optional[str] = None,
    ) -> Optional[DailyGoal]:
        """Update progress (0.0 to 1.0) and optional status for the target date's goal."""
        dt = target_date or self._today()
        goal = self.get_active_goal(dt)
        if not goal:
            return None

        new_progress = max(0.0, min(1.0, progress))
        new_status = status or ("completed" if new_progress >= 1.0 else "in_progress")
        now_iso = datetime.now(timezone.utc).isoformat()
        self._update_goal(goal.id, new_progress, new_status, notes or goal.notes, now_iso)
        return self.get_active_goal(dt)

    async def periodic_task_sweep_async(
        self,
        target_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform a periodic sweep over daily goals and task checkpoints."""
        goal = await self.get_active_goal_async(target_date)
        return self._sweep_result(goal, target_date)

    def periodic_task_sweep(
        self,
        target_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper for periodic task sweep."""
        goal = self.get_active_goal(target_date)
        return self._sweep_result(goal, target_date)

    def _sweep_result(
        self, goal: Optional[DailyGoal], target_date: Optional[str]
    ) -> dict[str, Any]:
        dt = target_date or self._today()
        sweep_result = {
            "sweep_timestamp": datetime.now(timezone.utc).isoformat(),
            "target_date": dt,
            "has_active_goal": goal is not None,
            "goal_title": goal.title if goal else None,
            "goal_progress": goal.progress if goal else 0.0,
            "goal_status": goal.status if goal else "none",
            "swept_items": 1 if goal else 0,
        }
        logger.info("Completed daily rhythm periodic task sweep: %s", sweep_result)
        return sweep_result

    def is_user_awake(self, dt: Optional[datetime] = None) -> bool:
        """Check if user is currently in their active waking window (09:00 to 00:00 midnight)."""
        check_dt = dt or datetime.now()
        hour = check_dt.hour
        # When sleep_hour is 0 (midnight), active awake window is 09:00 <= hour <= 23:59:59
        if self.sleep_hour == 0 or self.sleep_hour == 24:
            return hour >= self.wake_hour
        if self.wake_hour < self.sleep_hour:
            return self.wake_hour <= hour < self.sleep_hour
        return hour >= self.wake_hour or hour < self.sleep_hour

    def get_rhythm_phase(self, dt: Optional[datetime] = None) -> str:
        """Categorize current time into user's daily cognitive rhythm phase."""
        check_dt = dt or datetime.now()
        hour = check_dt.hour
        if not self.is_user_awake(check_dt):
            return "deep_rest"  # 00:00 - 08:59:59
        if 9 <= hour < 12:
            return "morning_focus"  # 09:00 - 11:59:59
        if 12 <= hour < 17:
            return "afternoon_execution"  # 12:00 - 16:59:59
        if 17 <= hour < 21:
            return "evening_momentum"  # 17:00 - 20:59:59
        return "night_reflection"  # 21:00 - 23:59:59

    def should_suppress_ambient_noise(self, dt: Optional[datetime] = None) -> bool:
        """Return True during deep rest hours to silence unprompted ambient chimes."""
        return not self.is_user_awake(dt)

    def get_schedule_summary(self, dt: Optional[datetime] = None) -> dict[str, Any]:
        """Return diagnostic metrics of user's active rhythm schedule."""
        check_dt = dt or datetime.now()
        awake = self.is_user_awake(check_dt)
        phase = self.get_rhythm_phase(check_dt)
        return {
            "user": self.user_name,
            "wake_time": f"{self.wake_hour:02d}:00",
            "sleep_time": f"{self.sleep_hour:02d}:00",
            "is_awake": awake,
            "current_phase": phase,
            "ambient_suppressed": not awake,
            "current_hour": check_dt.hour,
            "current_time": check_dt.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_morning_briefing(self) -> str:
        """Generate morning focus prompt tailored to Surendra's 09:00 start."""
        goal = self.get_active_goal()
        if goal:
            return (
                f"Good morning Surendra. Your #1 focus goal for today is: "
                f"'{goal.title}' ({int(goal.progress * 100)}% complete)."
            )
        return (
            "Good morning Surendra. What is your primary objective for today? "
            "You can say 'set daily goal <objective>'."
        )

    def get_evening_review(self) -> str:
        """Generate evening/night review and accountability check before midnight."""
        goal = self.get_active_goal()
        if not goal:
            return "Evening review: No primary goal was registered for today."

        pct = int(goal.progress * 100)
        if goal.status == "completed" or goal.progress >= 1.0:
            return f"Excellent work today Surendra! You accomplished your primary goal: '{goal.title}' (100% complete)."
        return (
            f"Evening review: Your goal today was '{goal.title}', currently at {pct}%. "
            f"Say 'goal done' to mark it complete, or we can carry it over to tomorrow."
        )


# Global instance
daily_rhythm = DailyRhythmManager()
