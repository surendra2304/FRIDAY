from pathlib import Path

from scripts.continuous_engineering_runner import (
    BRANCH_PREFIX,
    MIN_WORK_SECONDS,
    STATE_PREFIX,
    WORKSTREAMS,
    should_publish_code,
    task_instructions,
)


def test_workstreams_cover_exactly_ten_unique_agents() -> None:
    all_repositories = [name for repos in WORKSTREAMS.values() for name in repos]

    assert len(all_repositories) == 10
    assert len(set(all_repositories)) == 10
    assert set(all_repositories) == {
        "FRIDAY",
        "Inference",
        "Memora",
        "Stratex",
        "IntelX",
        "Futuris",
        "VyralX",
        "Forge",
        "Sentinel",
        "Cortex",
    }


def test_each_workstream_has_task_specific_continuation_instructions() -> None:
    for task in (1, 2, 3):
        instructions = task_instructions(task)
        assert f"Task {task}" in instructions
        assert "End-of-run obligations" in instructions


def test_each_session_runs_for_at_least_thirty_five_active_minutes() -> None:
    assert MIN_WORK_SECONDS == 35 * 60


def test_code_and_state_branches_are_separate() -> None:
    code_branches = {f"{BRANCH_PREFIX}-{task}" for task in WORKSTREAMS}
    state_branches = {f"{STATE_PREFIX}-{task}" for task in WORKSTREAMS}

    assert code_branches.isdisjoint(state_branches)



def test_successful_full_length_engineering_run_is_publishable() -> None:
    assert should_publish_code(
        {"publish_code": True, "active_seconds": MIN_WORK_SECONDS, "failure": None}
    )


def test_failed_or_short_engineering_run_never_publishes_code() -> None:
    assert not should_publish_code(
        {"publish_code": False, "active_seconds": MIN_WORK_SECONDS, "failure": "agent failed"}
    )
    assert not should_publish_code(
        {"publish_code": True, "active_seconds": MIN_WORK_SECONDS - 1}
    )
    assert not should_publish_code({"active_seconds": MIN_WORK_SECONDS})


def test_three_workflow_schedules_are_twenty_minutes_apart_in_ist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {1: "30 * * * *", 2: "50 * * * *", 3: "10 * * * *"}
    for task, cron in expected.items():
        path = root / ".github" / "workflows" / f"friday-universe-task-{task}.yml"
        workflow = path.read_text(encoding="utf-8")
        assert f"cron: '{cron}'" in workflow
        assert f"prepare --task {task}" in workflow
        assert f"run --task {task}" in workflow
        assert f"publish --task {task}" in workflow
        assert "cancel-in-progress: false" in workflow
