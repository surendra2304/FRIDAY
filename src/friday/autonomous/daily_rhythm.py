"""Daily Rhythm & Goal Accountability Manager for FRIDAY.

Adapted from Jarvis goals/rhythm.ts and accountability.ts.
Provides lightweight, local goal pursuit, morning intention planning, and evening reflection.

100% Free and Local: Backed by local SQLite database (~/.friday/goals.db).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from friday.core.logging import get_logger

logger = get_logger("autonomous.daily_rhythm")


@dataclass
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
    """Manages daily focus objectives, morning briefings, and evening check-ins."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if not db_path:
            base_dir = Path.home() / ".friday"
            base_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(base_dir / "goals.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
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
            logger.error("Failed to initialize goals DB: %s", e)

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # If an active goal for today already exists, update it; otherwise insert
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

        goal = self.get_active_goal(dt)
        logger.info("Set daily goal for %s: %s", dt, clean_title)
        return goal  # type: ignore

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

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE daily_goals
                SET progress = ?, status = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_progress, new_status, notes or goal.notes, now_iso, goal.id),
            )
            conn.commit()

        return self.get_active_goal(dt)

    def get_morning_briefing(self) -> str:
        """Generate morning focus prompt."""
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
        """Generate evening review and accountability check."""
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
