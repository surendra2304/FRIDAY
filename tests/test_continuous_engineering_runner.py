from scripts.continuous_engineering_runner import (
    BRANCH_PREFIX,
    MIN_WORK_SECONDS,
    STATE_PREFIX,
    WORKSTREAMS,
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


def test_each_session_requires_more_than_thirty_minutes_of_active_work() -> None:
    assert MIN_WORK_SECONDS > 30 * 60


def test_code_and_state_branches_are_separate() -> None:
    code_branches = {f"{BRANCH_PREFIX}-{task}" for task in WORKSTREAMS}
    state_branches = {f"{STATE_PREFIX}-{task}" for task in WORKSTREAMS}

    assert code_branches.isdisjoint(state_branches)
