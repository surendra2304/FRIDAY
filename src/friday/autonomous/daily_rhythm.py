"""Daily Rhythm & Goal Accountability Manager for FRIDAY.

Provides:
- Daily focus objectives, morning intention planning, and evening reflection.
- Primary persistence directly into `friday_db.daily_goals` in PostgreSQL via SQLAlchemy / asyncpg.
- Resilient local SQLite fallback (~/.friday/goals.db) for zero-downtime offline and unit testing.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    desc,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from friday.core.logging import get_logger

logger = get_logger("autonomous.daily_rhythm")

metadata = MetaData()
daily_goals_table = Table(
    "daily_goals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("goal_date", String(32), nullable=False, index=True),
    Column("title", String(512), nullable=False),
    Column("description", Text, default=""),
    Column("status", String(64), default="in_progress"),
    Column("progress", Float, default=0.0),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("notes", Text, default=""),
)


def get_postgres_dsn() -> str | None:
    """Resolve the Oracle Autonomous Database DSN (historical function name)."""
    raw_url = os.getenv("ORACLE_CORE_ASYNC_URL") or os.getenv("DATABASE_URL") or os.getenv("FRIDAY_DATABASE_URL")
    if raw_url:
        if raw_url.startswith("oracle://"):
            return raw_url.replace("oracle://", "oracle+oracledb://", 1)
        return raw_url
    return None


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

    Persists into Oracle Autonomous Database (``FRIDAY.daily_goals``) when a DSN
    is configured; an explicit ``db_path`` keeps SQLite available for isolated
    tests only.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        postgres_dsn: Optional[str] = None,
        enable_postgres: bool = True,
    ) -> None:
        if not db_path:
            from friday.core.database import get_ephemeral_db_path
            db_path = get_ephemeral_db_path("goals.db")
        self.db_path = db_path
        self._init_sqlite()

        self.postgres_dsn = postgres_dsn or get_postgres_dsn()
        self.enable_postgres = enable_postgres
        self._async_engine: Optional[AsyncEngine] = None
        self._postgres_available: Optional[bool] = None
        self._last_postgres_failure: float = 0.0
        self._postgres_retry_cooldown: float = 60.0

        # Surendra's Operating Rhythm: Awake 09:00 AM to 00:00 Midnight
        self.wake_hour: int = 9
        self.sleep_hour: int = 0
        self.user_name: str = "Surendra"

    def _init_sqlite(self) -> None:
        try:
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
        except Exception as e:
            logger.error("Failed to initialize SQLite goals DB: %s", e)

    def _can_try_postgres(self) -> bool:
        if not self.enable_postgres or not self.postgres_dsn:
            return False
        if self._postgres_available is False:
            import time
            if time.monotonic() - self._last_postgres_failure < self._postgres_retry_cooldown:
                return False
            # Cooldown expired, allow retry
            self._postgres_available = None
        return True

    def _get_engine(self) -> Optional[AsyncEngine]:
        if not self._can_try_postgres():
            return None
        if self._async_engine is None:
            try:
                self._async_engine = create_async_engine(
                    self.postgres_dsn,
                    echo=False,
                    pool_pre_ping=True,
                    connect_args={"tcp_connect_timeout": 2.0},
                )
            except Exception as e:
                logger.warning("Failed to create async engine for postgres: %s", e)
                self._async_engine = None
        return self._async_engine

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _sync_sqlite_set(self, dt: str, clean_title: str, description: str, now_iso: str) -> int:
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
                    """
                    UPDATE daily_goals
                    SET title = ?, description = ?, updated_at = ?, status = 'in_progress'
                    WHERE id = ?
                    """,
                    (clean_title, description, now_iso, gid),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO daily_goals (goal_date, title, description, status, progress, created_at, updated_at, notes)
                    VALUES (?, ?, ?, 'in_progress', 0.0, ?, ?, '')
                    """,
                    (dt, clean_title, description, now_iso, now_iso),
                )
                gid = cursor.lastrowid
            conn.commit()
            return gid

    def _sync_sqlite_update(self, gid: int, new_progress: float, new_status: str, notes: str, now_iso: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE daily_goals
                SET progress = ?, status = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_progress, new_status, notes, now_iso, gid),
            )
            conn.commit()

    async def set_daily_goal_async(
        self,
        title: str,
        description: str = "",
        target_date: Optional[str] = None,
    ) -> DailyGoal:
        """Set the primary focus goal for today (or target date) asynchronously in PostgreSQL."""
        dt = target_date or self._today()
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_title = title.strip()

        engine = self._get_engine()
        if engine is not None and self._postgres_available is not False:
            try:
                async with engine.begin() as conn:
                    stmt = select(daily_goals_table.c.id).where(
                        daily_goals_table.c.goal_date == dt
                    ).order_by(desc(daily_goals_table.c.id)).limit(1)
                    res = await conn.execute(stmt)
                    row = res.fetchone()
                    if row:
                        gid = row[0]
                        upd = (
                            update(daily_goals_table)
                            .where(daily_goals_table.c.id == gid)
                            .values(
                                title=clean_title,
                                description=description,
                                updated_at=now_iso,
                                status="in_progress",
                            )
                        )
                        await conn.execute(upd)
                    else:
                        ins = daily_goals_table.insert().values(
                            goal_date=dt,
                            title=clean_title,
                            description=description,
                            status="in_progress",
                            progress=0.0,
                            created_at=now_iso,
                            updated_at=now_iso,
                            notes="",
                        )
                        await conn.execute(ins)
                self._postgres_available = True
                logger.info("Persisted daily goal into PostgreSQL (friday_db.daily_goals): %s", clean_title)
                self._sync_sqlite_set(dt, clean_title, description, now_iso)
                goal = await self.get_active_goal_async(dt)
                if goal:
                    return goal
            except Exception as exc:
                import time
                logger.warning("PostgreSQL daily_goals persist failed, falling back to local SQLite: %s", exc)
                self._postgres_available = False
                self._last_postgres_failure = time.monotonic()

        # Fallback directly to local SQLite without re-triggering loop tasks
        self._sync_sqlite_set(dt, clean_title, description, now_iso)
        goal = self.get_active_goal(dt)
        return goal  # type: ignore

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
        self._sync_sqlite_set(dt, clean_title, description, now_iso)

        # Trigger async postgres sync if inside an active running loop
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.set_daily_goal_async(clean_title, description, dt))
        except RuntimeError:
            pass

        goal = self.get_active_goal(dt)
        logger.info("Set daily goal for %s: %s", dt, clean_title)
        return goal  # type: ignore

    async def get_active_goal_async(self, target_date: Optional[str] = None) -> Optional[DailyGoal]:
        """Get the active goal for today (or specified date) asynchronously."""
        dt = target_date or self._today()
        engine = self._get_engine()
        if engine is not None and self._postgres_available is not False:
            try:
                async with engine.connect() as conn:
                    stmt = select(daily_goals_table).where(
                        daily_goals_table.c.goal_date == dt
                    ).order_by(desc(daily_goals_table.c.id)).limit(1)
                    res = await conn.execute(stmt)
                    row = res.fetchone()
                    if row:
                        self._postgres_available = True
                        return DailyGoal(
                            id=row[0],
                            goal_date=row[1],
                            title=row[2],
                            description=row[3] or "",
                            status=row[4] or "in_progress",
                            progress=float(row[5] or 0.0),
                            created_at=str(row[6]),
                            updated_at=str(row[7]),
                            notes=row[8] or "",
                        )
            except Exception as exc:
                logger.warning("PostgreSQL get_active_goal failed, falling back to SQLite: %s", exc)
                self._postgres_available = False

        return self.get_active_goal(dt)

    def get_active_goal(self, target_date: Optional[str] = None) -> Optional[DailyGoal]:
        """Get the active goal for today (or specified date)."""
        dt = target_date or self._today()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, goal_date, title, description, status, progress, created_at, updated_at, notes
                FROM daily_goals
                WHERE goal_date = ?
                ORDER BY id DESC LIMIT 1
                """,
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

    async def update_goal_progress_async(
        self,
        progress: float,
        status: Optional[str] = None,
        notes: str = "",
        target_date: Optional[str] = None,
    ) -> Optional[DailyGoal]:
        """Update progress (0.0 to 1.0) and optional status asynchronously."""
        dt = target_date or self._today()
        new_progress = max(0.0, min(1.0, progress))
        new_status = status or ("completed" if new_progress >= 1.0 else "in_progress")
        now_iso = datetime.now(timezone.utc).isoformat()

        engine = self._get_engine()
        if engine is not None and self._postgres_available is not False:
            try:
                gid = None
                existing_notes = ""
                async with engine.begin() as conn:
                    stmt = select(daily_goals_table.c.id, daily_goals_table.c.notes).where(
                        daily_goals_table.c.goal_date == dt
                    ).order_by(desc(daily_goals_table.c.id)).limit(1)
                    res = await conn.execute(stmt)
                    row = res.fetchone()
                    if row:
                        gid = row[0]
                        existing_notes = row[1] or ""
                        upd = (
                            update(daily_goals_table)
                            .where(daily_goals_table.c.id == gid)
                            .values(
                                progress=new_progress,
                                status=new_status,
                                notes=notes or existing_notes,
                                updated_at=now_iso,
                            )
                        )
                        await conn.execute(upd)
                        self._postgres_available = True

                if gid is not None:
                    self._sync_sqlite_update(gid, new_progress, new_status, notes or existing_notes, now_iso)
                    goal = await self.get_active_goal_async(dt)
                    if goal:
                        return goal
            except Exception as exc:
                import time
                logger.warning("PostgreSQL update_goal_progress failed, falling back to SQLite: %s", exc)
                self._postgres_available = False
                self._last_postgres_failure = time.monotonic()

        # Fallback directly to local SQLite without re-triggering loop tasks
        fallback_goal = self.get_active_goal(dt)
        if not fallback_goal:
            return None
        self._sync_sqlite_update(fallback_goal.id, new_progress, new_status, notes or fallback_goal.notes, now_iso)
        return self.get_active_goal(dt)

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

        self._sync_sqlite_update(goal.id, new_progress, new_status, notes or goal.notes, now_iso)

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.update_goal_progress_async(new_progress, new_status, notes, dt))
        except RuntimeError:
            pass

        return self.get_active_goal(dt)

    async def periodic_task_sweep_async(
        self,
        target_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform a periodic sweep over daily goals and task checkpoints."""
        dt = target_date or self._today()
        goal = await self.get_active_goal_async(dt)
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

    def periodic_task_sweep(
        self,
        target_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper for periodic task sweep."""
        dt = target_date or self._today()
        goal = self.get_active_goal(dt)
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
