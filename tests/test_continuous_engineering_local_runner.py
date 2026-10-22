from __future__ import annotations

from pathlib import Path

from scripts.continuous_engineering_local_runner import (
    HANDOFF_DIR,
    MIN_WORK_SECONDS,
    branch_for,
    handoff_paths,
)


def test_workstream_branches_are_stable_and_separate() -> None:
    branches = {task: branch_for(task) for task in (1, 2, 3)}

    assert branches[1] == "automation/friday-universe-task-1"
    assert branches[2] == "automation/friday-universe-task-2"
    assert branches[3] == "automation/friday-universe-task-3"
    assert len(set(branches.values())) == 3


def test_work_session_requires_more_than_thirty_minutes() -> None:
    assert MIN_WORK_SECONDS > 30 * 60


def test_each_task_gets_distinct_persistent_handoff_files(tmp_path: Path) -> None:
    all_files: list[Path] = []

    for task in (1, 2, 3):
        checkpoint, next_prompt, last_run = handoff_paths(tmp_path, task)
        all_files.extend((checkpoint, next_prompt, last_run))

        assert checkpoint.parent == tmp_path / HANDOFF_DIR
        assert checkpoint.name == f"task-{task}-checkpoint.md"
        assert next_prompt.name == f"task-{task}-next-run.md"
        assert last_run.name == f"task-{task}-last-run.json"
        assert checkpoint.parent.is_dir()

    assert len(set(all_files)) == 9


def test_handoff_contract_explicitly_separates_checkpoint_and_next_prompt(tmp_path: Path) -> None:
    checkpoint, next_prompt, last_run = handoff_paths(tmp_path, 2)

    assert checkpoint != next_prompt
    assert next_prompt != last_run
    assert "next-run" in next_prompt.name
    assert "checkpoint" in checkpoint.name
