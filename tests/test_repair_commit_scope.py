"""A repair commit must contain the repair, and nothing else.

This is a regression test for a defect found by running the autonomous loop on a
real repository rather than by reading the code. `GitRepairApplier.commit_all`
ran ``git add -A``, so the repair commit swept up whatever else happened to be
dirty: the reflex brain's own state file, ``__pycache__/*.pyc``, and the owner's
unrelated work in progress. Nothing warned; the commit simply contained more
than the receipt said it did.

An unattended agent committing files nobody asked it to change is the exact
failure mode the whole gate exists to prevent, and it was on the far side of the
gate, where nothing was looking.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.autonomous.self_repair import GitRepairApplier

BROKEN = """\
def add_all(values):
    total = 0
    for value in values:
        total += value
    return totl
"""
FIXED = """\
def add_all(values):
    total = 0
    for value in values:
        total += value
    return total
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "friday").mkdir(parents=True)
    (repo / "src" / "friday" / "calc.py").write_text(BROKEN, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "owner@example.invalid")
    _git(repo, "config", "user.name", "Owner")
    (repo / ".gitignore").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the broken starting point")
    return repo


def test_a_repair_commit_contains_only_the_repaired_file(repo: Path) -> None:
    # The owner is in the middle of something unrelated...
    (repo / "notes.md").write_text("unfinished thinking\n", encoding="utf-8")
    # ...and the agent's own runtime has left state lying around.
    (repo / "gate_state.json").write_text('{"passes": 3}\n', encoding="utf-8")
    (repo / "src" / "friday" / "__pycache__").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "friday" / "__pycache__" / "calc.cpython-311.pyc").write_bytes(b"\x00\x01")

    applier = GitRepairApplier(str(repo))
    applier.create_branch(applier.current_commit() or "HEAD", "reflex/repair-probe")
    applier.apply_snippet("src/friday/calc.py", "    return totl", "    return total")
    commit = applier.commit_touched("repair: `totl` is not defined")

    changed = _git(repo, "show", "--name-only", "--pretty=format:", commit).split()
    assert changed == ["src/friday/calc.py"], (
        "the repair commit must contain the repaired file and nothing else"
    )

    # The owner's work and the agent's own state are still exactly where they were,
    # untracked or dirty, for the owner to deal with as they choose.
    status = _git(repo, "status", "--porcelain")
    assert "?? notes.md" in status
    assert "?? gate_state.json" in status
    assert "gate_state.json" not in changed
    assert (repo / "notes.md").read_text(encoding="utf-8") == "unfinished thinking\n"


def test_committing_nothing_of_its_own_is_refused_rather_than_sweeping(repo: Path) -> None:
    (repo / "notes.md").write_text("unfinished thinking\n", encoding="utf-8")
    applier = GitRepairApplier(str(repo))
    head_before = applier.current_commit()

    with pytest.raises(RuntimeError, match="has not rewritten any file"):
        applier.commit_touched("repair: nothing at all")

    assert applier.current_commit() == head_before, "a refusal must not create a commit"
    assert "?? notes.md" in _git(repo, "status", "--porcelain")


def test_the_deprecated_name_behaves_like_the_safe_one(repo: Path) -> None:
    (repo / "notes.md").write_text("unfinished thinking\n", encoding="utf-8")
    applier = GitRepairApplier(str(repo))
    applier.create_branch(applier.current_commit() or "HEAD", "reflex/repair-probe-2")
    applier.apply_snippet("src/friday/calc.py", "    return totl", "    return total")

    commit = applier.commit_all("repair: keep the old name working")

    changed = _git(repo, "show", "--name-only", "--pretty=format:", commit).split()
    assert changed == ["src/friday/calc.py"]
    assert "?? notes.md" in _git(repo, "status", "--porcelain")


def test_two_repairs_in_one_session_stage_both_and_still_nothing_else(repo: Path) -> None:
    (repo / "other.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "notes.md").write_text("unfinished thinking\n", encoding="utf-8")
    applier = GitRepairApplier(str(repo))
    applier.create_branch(applier.current_commit() or "HEAD", "reflex/repair-probe-3")

    applier.apply_snippet("src/friday/calc.py", "    return totl", "    return total")
    applier.apply_snippet("other.py", "value = 1", "value = 2")
    commit = applier.commit_touched("repair: two files, deliberately")

    changed = sorted(_git(repo, "show", "--name-only", "--pretty=format:", commit).split())
    assert changed == ["other.py", "src/friday/calc.py"]
    assert "?? notes.md" in _git(repo, "status", "--porcelain")
