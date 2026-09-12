"""Unit tests for Daily Rhythm & Goal Accountability."""

import os
import tempfile
import pytest

from friday.autonomous.daily_rhythm import DailyRhythmManager
from friday.devices.windows_friday import windows_friday


@pytest.fixture
def temp_rhythm() -> DailyRhythmManager:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name
    mgr = DailyRhythmManager(db_path=tmp_path)
    yield mgr
    try:
        os.remove(tmp_path)
    except Exception:
        pass


def test_daily_rhythm_goal_lifecycle(temp_rhythm: DailyRhythmManager) -> None:
    # 1. Set goal
    goal = temp_rhythm.set_daily_goal(
        title="Complete Universal Repository Integration",
        description="Ship jarvis integration with 100% free sources",
    )
    assert goal is not None
    assert goal.title == "Complete Universal Repository Integration"
    assert goal.status == "in_progress"
    assert goal.progress == 0.0

    # 2. Retrieve active goal
    active = temp_rhythm.get_active_goal()
    assert active is not None
    assert active.id == goal.id

    # 3. Morning briefing contains goal
    briefing = temp_rhythm.get_morning_briefing()
    assert "Complete Universal Repository Integration" in briefing

    # 4. Update progress
    updated = temp_rhythm.update_goal_progress(0.75, notes="Tests passing")
    assert updated is not None
    assert updated.progress == 0.75
    assert updated.status == "in_progress"

    # 5. Complete goal
    completed = temp_rhythm.update_goal_progress(1.0)
    assert completed is not None
    assert completed.progress == 1.0
    assert completed.status == "completed"

    # 6. Evening review acknowledges completion
    review = temp_rhythm.get_evening_review()
    assert "Excellent work" in review
    assert "100% complete" in review


def test_windows_friday_goal_and_window_directives() -> None:
    # 1. Goal directive can_handle
    assert windows_friday.can_handle("set daily goal write clean tests") is True
    assert windows_friday.can_handle("my goal") is True
    assert windows_friday.can_handle("goal done") is True
    assert windows_friday.can_handle("morning briefing") is True
    assert windows_friday.can_handle("evening review") is True

    # 2. Imperative window control directives can_handle
    assert windows_friday.can_handle("minimize window") is True
    assert windows_friday.can_handle("maximize window") is True
    assert windows_friday.can_handle("restore window") is True
    assert windows_friday.can_handle("close window") is True
    assert windows_friday.can_handle("tidy up windows") is True

    # 3. Execute goal directive
    handled, reply, meta = windows_friday.handle_directive("set daily goal ship friday v2")
    assert handled is True
    assert meta["action"] == "set_daily_goal"
    assert "ship friday v2" in reply

    handled2, reply2, meta2 = windows_friday.handle_directive("my goal")
    assert handled2 is True
    assert meta2["action"] == "get_daily_goal"
    assert "ship friday v2" in reply2
