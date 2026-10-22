"""A repair branch left behind must not make the next repair impossible.

Found by running the capability install twice on a real repository: the first attempt
created `capability/count_words_note_paste`, its work was reset away, and the second
attempt died with

    apply was refused: GIT_FAILED: git checkout -b failed: fatal: a branch named
    'capability/count_words_note_paste' already exists

The owner is told the *installation* was refused, which is not what happened, and
there is no way forward from inside FRIDAY. Two rules fix it, and the second one is
the one that matters: an earlier attempt's branch may be reused only when moving it
would lose nothing; otherwise the repair takes the next free name, because the
commits of a rolled-back attempt are still evidence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.autonomous.self_repair import GitRepairApplier


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# the owner's repository\n", encoding="utf-8")
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "o@example.invalid")
    _git(path, "config", "user.name", "Owner")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "base")
    return path


def test_a_free_branch_name_is_used_unchanged(repo: Path) -> None:
    applier = GitRepairApplier(str(repo))
    base = applier.current_commit()

    name, commit = applier.create_branch(base, "capability/count_words")

    assert name == "capability/count_words"
    assert commit == base
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == name


def test_a_stale_branch_contained_in_the_base_is_reused(repo: Path) -> None:
    """The leftover of an attempt that added nothing is not a reason to refuse work."""
    applier = GitRepairApplier(str(repo))
    base = applier.current_commit()
    applier.create_branch(base, "capability/count_words")
    _git(repo, "checkout", "-q", "main")

    name, commit = applier.create_branch(base, "capability/count_words")

    assert name == "capability/count_words", "a harmless leftover blocked the repair"
    assert commit == base
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == name


def test_a_branch_holding_earlier_work_is_left_alone(repo: Path) -> None:
    """An earlier attempt's commits survive; the new attempt takes the next name."""
    applier = GitRepairApplier(str(repo))
    base = applier.current_commit()
    applier.create_branch(base, "capability/count_words")
    (repo / "attempt_one.py").write_text("print('first attempt')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "repair(patch_0001): the first attempt")
    earlier = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")

    name, commit = applier.create_branch(base, "capability/count_words")

    assert name == "capability/count_words-2", name
    assert commit == base
    # The earlier attempt is untouched, at the commit it had, and still reachable -
    # on its own branch, which is where a rolled-back attempt's evidence belongs.
    assert _git(repo, "rev-parse", "capability/count_words") == earlier
    assert "first attempt" in _git(repo, "show", "capability/count_words:attempt_one.py")
    assert not (repo / "attempt_one.py").exists(), "the new branch inherited a stranger's file"


def test_the_installed_commit_records_the_branch_it_actually_used(repo: Path) -> None:
    """A rename must be reported, not hidden: the receipt is evidence."""
    applier = GitRepairApplier(str(repo))
    base = applier.current_commit()
    applier.create_branch(base, "capability/count_words")
    (repo / "first.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    _git(repo, "checkout", "-q", "main")

    name, _ = applier.create_branch(base, "capability/count_words")
    (repo / "second.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "repair(patch_0002): the second attempt")

    branches = _git(repo, "branch", "--list", "capability/*").replace("*", "").split()
    assert sorted(branches) == ["capability/count_words", "capability/count_words-2"]
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == name
    # Both attempts are on their own branch, neither overwritten.
    assert _git(repo, "show", "--stat", "--oneline", "capability/count_words") != ""
    assert "second.py" in _git(repo, "show", "--stat", "--oneline", name)


def test_the_search_for_a_free_name_does_not_wander(repo: Path) -> None:
    """Twenty taken names is a refusal with a reason, not an infinite loop."""
    applier = GitRepairApplier(str(repo))
    base = applier.current_commit()
    for suffix in ("", *(f"-{n}" for n in range(2, 21))):
        applier.create_branch(base, f"capability/taken{suffix}")
        (repo / f"file{suffix or '0'}.py").write_text("x = 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"attempt {suffix}")
        _git(repo, "checkout", "-q", "main")

    with pytest.raises(RuntimeError) as caught:
        applier.create_branch(base, "capability/taken")

    message = str(caught.value)
    assert "all exist" in message
    assert "nothing was written" in message
