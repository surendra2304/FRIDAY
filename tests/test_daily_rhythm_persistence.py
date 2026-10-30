"""Unit tests for the Autonomous Daily Rhythm engine and its persistence paths."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from friday.autonomous.daily_rhythm import (
    DailyGoal,
    DailyRhythmManager,
    daily_goals_table,
    get_postgres_dsn,
    metadata,
)
from friday.planning.executors import BaseExecutor, ExecutorRegistry, ExecutorResult
from friday.planning.scheduler import TaskGraphScheduler
from friday.planning.types import TaskGraph, TaskStep


def test_get_postgres_dsn_resolution():
    """Verify get_postgres_dsn resolves Oracle DSNs and never invents a fallback."""
    oracle_dsn = "oracle+oracledb://FRIDAY:pass@adb.example.com:1522/?service_name=TEST"
    with patch.dict(os.environ, {"DATABASE_URL": oracle_dsn}):
        assert get_postgres_dsn() == oracle_dsn

    with patch.dict(
        os.environ,
        {"DATABASE_URL": "", "FRIDAY_DATABASE_URL": "", "ORACLE_CORE_ASYNC_URL": ""},
    ):
        assert get_postgres_dsn() is None


def test_daily_rhythm_waking_schedule_and_phases():
    """Verify Surendra's active waking window (09:00 to 00:00 midnight) and phase transitions."""
    manager = DailyRhythmManager()
    assert manager.wake_hour == 9
    assert manager.sleep_hour == 0

    # Test awake state across hours
    from datetime import datetime
    dt_morning = datetime(2026, 10, 21, 9, 30)
    assert manager.is_user_awake(dt_morning) is True
    assert manager.get_rhythm_phase(dt_morning) == "morning_focus"
    assert manager.should_suppress_ambient_noise(dt_morning) is False

    dt_afternoon = datetime(2026, 10, 21, 14, 0)
    assert manager.is_user_awake(dt_afternoon) is True
    assert manager.get_rhythm_phase(dt_afternoon) == "afternoon_execution"

    dt_evening = datetime(2026, 10, 21, 19, 0)
    assert manager.is_user_awake(dt_evening) is True
    assert manager.get_rhythm_phase(dt_evening) == "evening_momentum"

    dt_night = datetime(2026, 10, 21, 23, 15)
    assert manager.is_user_awake(dt_night) is True
    assert manager.get_rhythm_phase(dt_night) == "night_reflection"

    # Deep rest hours (00:00 to 08:59)
    dt_sleep_early = datetime(2026, 10, 21, 2, 0)
    assert manager.is_user_awake(dt_sleep_early) is False
    assert manager.get_rhythm_phase(dt_sleep_early) == "deep_rest"
    assert manager.should_suppress_ambient_noise(dt_sleep_early) is True

    dt_sleep_late = datetime(2026, 10, 21, 8, 45)
    assert manager.is_user_awake(dt_sleep_late) is False
    assert manager.get_rhythm_phase(dt_sleep_late) == "deep_rest"
    assert manager.should_suppress_ambient_noise(dt_sleep_late) is True

    summary = manager.get_schedule_summary(dt_morning)
    assert summary["wake_time"] == "09:00"
    assert summary["sleep_time"] == "00:00"
    assert summary["is_awake"] is True


@pytest.mark.asyncio
async def test_daily_rhythm_sqlite_fallback_lifecycle():
    """Verify DailyRhythmManager operates reliably under SQLite fallback."""
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test_goals.db")

    try:
        manager = DailyRhythmManager(db_path=db_path, enable_postgres=False)

        # 1. Set daily goal
        goal = manager.set_daily_goal("Achieve Tier-1 Autonomy", "Full universe mesh integration")
        assert goal.title == "Achieve Tier-1 Autonomy"
        assert goal.progress == 0.0
        assert goal.status == "in_progress"

        # 2. Get active goal
        active = manager.get_active_goal()
        assert active is not None
        assert active.title == "Achieve Tier-1 Autonomy"

        # 3. Update goal progress
        updated = manager.update_goal_progress(0.75, notes="Phase 2 complete")
        assert updated is not None
        assert updated.progress == 0.75
        assert updated.notes == "Phase 2 complete"
        assert updated.status == "in_progress"

        # 4. Mark complete
        completed = manager.update_goal_progress(1.0)
        assert completed is not None
        assert completed.status == "completed"

        # 5. Periodic task sweep
        sweep = manager.periodic_task_sweep()
        assert sweep["has_active_goal"] is True
        assert sweep["goal_status"] == "completed"

        # 6. Morning briefing and evening review
        briefing = manager.get_morning_briefing()
        assert "Achieve Tier-1 Autonomy" in briefing
        review = manager.get_evening_review()
        assert "Excellent work" in review

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_daily_rhythm_async_sqlalchemy_engine():
    """Verify DailyRhythmManager executes async SQLAlchemy operations over an async engine."""
    tmp_dir = tempfile.mkdtemp()
    sqlite_db_path = os.path.join(tmp_dir, "local_goals.db")

    # Use a separate file for the async SQLAlchemy mock engine
    engine_file = os.path.join(tmp_dir, "async_pg_mock.db")
    test_dsn = f"sqlite+aiosqlite:///{engine_file}"
    test_engine = create_async_engine(test_dsn, echo=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    try:
        manager = DailyRhythmManager(db_path=sqlite_db_path, enable_postgres=True)
        manager._async_engine = test_engine
        manager._postgres_available = True

        # Async set goal
        goal = await manager.set_daily_goal_async(
            title="Async Postgres Goal",
            description="Testing SQLAlchemy asyncpg pipeline",
        )
        assert goal.title == "Async Postgres Goal"
        assert goal.status == "in_progress"

        # Async get goal
        retrieved = await manager.get_active_goal_async()
        assert retrieved is not None
        assert retrieved.title == "Async Postgres Goal"

        # Async update goal
        updated = await manager.update_goal_progress_async(0.8, notes="80% reached")
        assert updated is not None
        assert updated.progress == 0.8
        assert "80%" in updated.notes

        # Async periodic task sweep
        sweep = await manager.periodic_task_sweep_async()
        assert sweep["has_active_goal"] is True
        assert sweep["goal_title"] == "Async Postgres Goal"

    finally:
        await test_engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


class DummyExecutor(BaseExecutor):
    def __init__(self) -> None:
        super().__init__(
            name="dummy_exec",
            capability="dummy",
            description="Dummy executor for test",
        )

    def execute(self, inputs: dict, context: dict | None = None) -> ExecutorResult:
        return ExecutorResult(success=True, output="done")


def test_scheduler_integrates_daily_rhythm_and_sweeps():
    """Verify TaskGraphScheduler registers initial goal and persists completion progress."""
    registry = ExecutorRegistry(register_defaults=False)
    registry.register(DummyExecutor())

    scheduler = TaskGraphScheduler(executor_registry=registry)
    graph = TaskGraph(goal="Build Automated CI Pipeline")
    graph.add_task(
        TaskStep(
            id="task_1",
            description="Run unit test suite",
            selected_executor="dummy_exec",
        )
    )

    with patch("friday.autonomous.daily_rhythm.daily_rhythm.set_daily_goal") as mock_set:
        with patch("friday.autonomous.daily_rhythm.daily_rhythm.update_goal_progress") as mock_update:
            with patch("friday.autonomous.daily_rhythm.daily_rhythm.periodic_task_sweep") as mock_sweep:
                completed_graph = scheduler.execute_graph(graph)
                assert completed_graph.is_successful()
                mock_set.assert_called_once()
                mock_update.assert_called_once()
                mock_sweep.assert_called_once()
