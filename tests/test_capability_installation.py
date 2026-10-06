"""A capability FRIDAY has never had, installed through the gate — for real.

The defect this pins: `ToolSynthesiser` wrote a brand-new tool file straight into
the working tree and its report claimed the tool "reaches the repository through the
same gate as any other change". Nothing carried it there. A file that appears in a
tree with no commit, no review and no mandate is ungoverned self-modification.

These tests use a real git checkout, the real gate, the real reviewer, the real
mandate authority and the real smoke test. Nothing here asserts a claim from the
code's own prose: success is checked by importing the installed file in a fresh
interpreter and by reading the commit out of the repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.autonomous.self_repair import GitRepairApplier, SelfRepairGate
from friday.cognition.installation import MAX_NEW_TOOL_LINES, CapabilityInstaller
from friday.cognition.mandate import MandateAuthority, MandateLedger
from friday.cognition.reviewer import MAX_REPLACEMENT_LINES, LocalReviewer

REVIEW_KEY = b"installation-review-key"
MANDATE_KEY = b"installation-mandate-key"

TOOL_PATH = "src/friday/tools/builtin/count_words_in_note.py"

CANDIDATE = '''"""A tool that counts the words in a note."""

from __future__ import annotations

from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class CountWordsInNoteTool(BaseTool):
    """Count the words in a note."""

    name = "count_words_in_note"
    description = "Count the words in a note."
    safety_level = SafetyLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"input": {"type": "string"}},
    }

    def execute(self, input: str = "", **_: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=str(len(input.split())),
            safety_level=self.safety_level,
        )
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / "src/friday/tools/builtin").mkdir(parents=True)
    (path / "README.md").write_text("# the owner's repository\n", encoding="utf-8")
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "o@example.invalid")
    _git(path, "config", "user.name", "Owner")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "base")
    return path


def _installer(repo: Path, *, mandate: bool = True, paths: tuple[str, ...] = ("src/**",)) -> CapabilityInstaller:
    gate = SelfRepairGate(GitRepairApplier(str(repo)), review_verification_key=REVIEW_KEY)
    authority = None
    if mandate:
        import time as _time

        from friday.cognition.mandate import AutonomyMandate

        active = AutonomyMandate(
            issued_by="Surendra",
            scopes=("source_repair",),
            allowed_paths=paths,
            expires_at=_time.time() + 3600,   # the field is an epoch, not a datetime
        )
        # sign() returns the signed document; to_document() has no signature and
        # the ledger verifies what it stores, so storing the unsigned shape was
        # how this fixture produced "no active mandate" with a valid key.
        signed = active.sign(MANDATE_KEY)
        ledger = MandateLedger(str(repo / "mandates.json"))
        ledger.record_grant(signed)
        authority = MandateAuthority(key=MANDATE_KEY, ledger=ledger)
    return CapabilityInstaller(
        repo,
        gate=gate,
        authority=authority,
        reviewer=LocalReviewer(REVIEW_KEY, reviewer_id="sentinel"),
    )


def test_an_authorised_capability_is_installed_reviewed_and_committed(repo: Path) -> None:
    installer = _installer(repo)
    destination = repo / TOOL_PATH
    smoke = installer.smoke_test(repo / TOOL_PATH, "count_words_in_note")  # no file yet: fails
    assert smoke["ok"] is False, "the smoke test claimed a file that does not exist"

    # The candidate is verified where a candidate can honestly be verified: written
    # to a scratch copy of the same layout would be ideal, but the true pre-install
    # check the synthesiser performs is the same driver on a staged path, so the
    # evidence below is produced the same way.
    staging = repo / ".." / "staging_tool.py"
    staging.write_text(CANDIDATE, encoding="utf-8")
    pre = installer.smoke_test(staging, "count_words_in_note")
    assert pre["ok"] is True, pre

    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install count_words_in_note for the owner's request",
        smoke_check={**pre, "command": "smoke test in a fresh interpreter"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "COMPLETED", outcome.as_dict()
    assert outcome.reachable is True
    assert destination.is_file(), "the tool was reported installed and is not on disk"

    # It is committed, the commit contains exactly this file, and the work is on the
    # branch the owner was on — the capability branch remains as the evidence of how
    # the tool arrived. A fresh clone with no git identity once ended up parked on
    # capability/sum_numbers with the tools staged and uncommitted; this is the test
    # that keeps that from coming back.
    head = _git(repo, "rev-parse", "HEAD")
    assert head == outcome.commit
    assert _git(repo, "branch", "--show-current") == "main", (
        "the install left the repository checked out on the capability branch"
    )
    assert _git(repo, "rev-parse", "capability/count_words_in_note") == outcome.commit
    # Nothing staged, nothing modified, and the tool itself is committed rather than
    # sitting untracked. (Bytecode caches are ignored here: they are a byproduct of
    # importing the tool, not a claim about the repository's contents.)
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == "", (
        "the install left files staged or modified in the owner's tree"
    )
    assert _git(repo, "status", "--porcelain", "--", TOOL_PATH) == "", (
        "the installed tool is not committed"
    )
    changed = _git(repo, "show", "--name-only", "--pretty=format:", head).split()
    assert changed == [TOOL_PATH], f"the install commit touched {changed}"

    # And it really imports and runs in a fresh interpreter.
    verify = installer.smoke_test(destination, "count_words_in_note")
    assert verify["ok"] is True, verify
    assert verify["checks"] == [
        "imports_cleanly",
        "instantiates",
        "schema_valid",
        "returns_tool_result",
    ]


def test_without_a_mandate_the_candidate_stops_at_the_gate(repo: Path) -> None:
    installer = _installer(repo, mandate=False)
    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check={"ok": True, "checks": ["syntax_valid"], "detail": "the tool ran"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "AWAITING_MANDATE", outcome.as_dict()
    assert outcome.gate_step == "authority"
    assert "--approve-repair" in outcome.detail
    assert not (repo / TOOL_PATH).exists(), "a capability was installed without authority"
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-list", "--max-parents=0", "HEAD")


def test_a_mandate_that_does_not_cover_the_path_installs_nothing(repo: Path) -> None:
    installer = _installer(repo, paths=("docs/**",))
    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check={"ok": True, "checks": ["syntax_valid"], "detail": "the tool ran"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "AWAITING_MANDATE"
    assert "FILE_NOT_PERMITTED" in outcome.detail or "SCOPE" in outcome.detail, outcome.detail
    assert not (repo / TOOL_PATH).exists()


def test_a_candidate_that_fails_its_smoke_test_is_never_proposed(repo: Path) -> None:
    installer = _installer(repo)
    outcome = installer.install(
        tool_name="count_words_in_note",
        source="this is not python",
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check={"ok": False, "checks": [], "detail": "the generated tool does not parse"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "REFUSED"
    assert outcome.gate_step == "propose"
    assert "smoke test" in outcome.detail
    assert not (repo / TOOL_PATH).exists()


def test_a_candidate_carrying_a_secret_is_refused_by_the_real_reviewer(repo: Path) -> None:
    """The reviewer's secret scan is not bypassed for self-authored code.

    The payload is a real-shaped key and not a placeholder, because the reviewer's
    allowlist deliberately admits things like ``...EXAMPLE`` in documentation.
    """
    installer = _installer(repo)
    leaking = CANDIDATE.replace(
        "        return ToolResult("
        "\n            name=self.name,"
        "\n            content=str(len(input.split())),"
        "\n            safety_level=self.safety_level,"
        "\n        )",
        # Not "AKIA...EXAMPLE": the reviewer's allowlist deliberately lets
        # placeholders through, so a test using one would prove nothing.
        '        AWS_KEY = "AKIAQWERTYUIOPASDFGH"'
        '\n        return ToolResult('
        "\n            name=self.name, content=AWS_KEY, safety_level=self.safety_level"
        "\n        )",
    )
    staging = repo / ".." / "leaking_tool.py"
    staging.write_text(leaking, encoding="utf-8")
    pre = installer.smoke_test(staging, "count_words_in_note")
    assert pre["ok"] is True, "the leak detector is the reviewer's job, not the smoke test's"

    outcome = installer.install(
        tool_name="count_words_in_note",
        source=leaking,
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check=pre,
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "REVIEW_REJECTED", outcome.as_dict()
    assert not (repo / TOOL_PATH).exists()


def test_the_install_reviewer_may_clear_a_whole_new_file(repo: Path) -> None:
    """A new tool is a file, not a diff, so the replacement bound is raised visibly.

    The raise is deliberate and bounded: a default reviewer refuses the same
    candidate as too large, which is what the repair pipeline must keep doing.
    """
    filing = CANDIDATE + "\n".join(f"# note {index}" for index in range(80)) + "\n"
    filler = "\n".join(f"def helper_{i}():\n    return {i}\n" for i in range(40))
    big = CANDIDATE + "\n\n" + filler

    default = LocalReviewer(REVIEW_KEY)
    strict = default.review(
        patch_fingerprint="f" * 64,
        target_file=TOOL_PATH,
        replacement_snippet=big,
        original_snippet="",
        current_source="",
        test_evidence={"command": "smoke test", "passed": True},
    )
    assert strict.cleared is False
    assert any("limit this reviewer was built with" in reason for reason in strict.reasons)

    raised = CapabilityInstaller(repo, reviewer=LocalReviewer(REVIEW_KEY, max_replacement_lines=MAX_NEW_TOOL_LINES))._reviewer_or_build()
    generous = raised.review(
        patch_fingerprint="f" * 64,
        target_file=TOOL_PATH,
        replacement_snippet=big,
        original_snippet="",
        current_source="",
        test_evidence={"command": "smoke test", "passed": True},
    )
    assert generous.cleared is True, generous.reasons
    assert MAX_NEW_TOOL_LINES > MAX_REPLACEMENT_LINES
    assert filing  # the comment-only variant exists for contrast


def test_an_existing_file_is_never_overwritten(repo: Path) -> None:
    installer = _installer(repo)
    (repo / TOOL_PATH).write_text("# the owner's own tool\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the owner's tool")

    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check={"ok": True, "checks": ["syntax_valid"], "detail": "the tool ran"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "REFUSED"
    assert "refusing to overwrite" in outcome.detail
    assert (repo / TOOL_PATH).read_text(encoding="utf-8") == "# the owner's own tool\n"


def test_verification_on_the_applied_tree_rolls_back_a_bad_install(repo: Path) -> None:
    """The install is verified where it landed, and undone if it fails there.

    The candidate is genuinely sensitive to the tree it is verified in: it refuses
    to run when the repository's HEAD is an installation commit, which is exactly
    the state the apply step creates. So it passes the pre-install check on the
    base commit and fails the applied-tree check, with no mocking involved.
    """
    sensitive = CANDIDATE.replace(
        "        return ToolResult("
        "\n            name=self.name,"
        "\n            content=str(len(input.split())),"
        "\n            safety_level=self.safety_level,"
        "\n        )",
        '''        import subprocess

        head = subprocess.run(
            ["git", "log", "-1", "--pretty=%s"], capture_output=True, text=True
        ).stdout.strip()
        if head.startswith("repair("):
            raise RuntimeError("this tool refuses to run in a repository mid-install")
        return ToolResult(
            name=self.name,
            content=str(len(input.split())),
            safety_level=self.safety_level,
        )''',
    )
    installer = _installer(repo)
    staging = repo / ".." / "sensitive_tool.py"
    staging.write_text(sensitive, encoding="utf-8")
    pre = installer.smoke_test(staging, "count_words_in_note")
    assert pre["ok"] is True, pre
    base = _git(repo, "rev-parse", "HEAD")

    outcome = installer.install(
        tool_name="count_words_in_note",
        source=sensitive,
        capability="count the words in a note",
        rationale="install for the owner",
        smoke_check=pre,
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "ROLLED_BACK", outcome.as_dict()
    assert not (repo / TOOL_PATH).exists(), "a rolled-back install left its file behind"
    assert _git(repo, "rev-parse", "HEAD") != base, "the revert is itself a commit"
    assert "Revert" in _git(repo, "log", "-1", "--pretty=%s")


# ── the author's own example, on the tree that will actually import it ───────


class _NoModel:
    def generate(self, *args, **kwargs):
        raise RuntimeError("no egress from here")


def _composed_candidate(repo: Path, request: str) -> tuple[dict, str, str]:
    """Synthesise offline, the way the resolver does, and return (item, source, path)."""
    from friday.cognition.capability import CapabilityResolver

    resolution = CapabilityResolver(llm=_NoModel(), repository_root=repo).resolve(request)
    assert resolution.synthesised, resolution.as_dict()
    item = resolution.synthesised[0]
    return item, item["source"], item["path"]


def test_a_composed_tool_is_installed_and_its_example_holds_where_it_landed(repo: Path) -> None:
    """Offline composition, all the way through the real gate, checked on the real file.

    The point of the example is that it is checked twice: once against the candidate
    before the gate sees it, and once against the file that actually landed. A tool
    that only behaves before installation is a tool that does not work.
    """
    item, source, relative = _composed_candidate(repo, "count the words in a note I paste in")
    assert item["authorship"].startswith("local_composition:"), item["authorship"]
    assert item["self_test"], item

    installer = _installer(repo)
    tool_name = item["tool"]
    staging = repo / ".." / f"{tool_name}.py"
    staging.write_text(source, encoding="utf-8")
    pre = installer.smoke_test(staging, tool_name, self_test=item["self_test"])
    assert pre["ok"] is True, pre
    assert "behaves_as_specified" in pre["checks"], pre

    outcome = installer.install(
        tool_name=tool_name,
        source=source,
        capability=item["capability"],
        rationale="install a capability FRIDAY composed offline",
        smoke_check=pre,
        relative_path=relative,
        self_test=item["self_test"],
    )

    assert outcome.outcome == "COMPLETED", outcome.as_dict()
    applied = outcome.verification["applied_tree"]
    assert applied["ok"] is True, applied
    assert "behaves_as_specified" in applied["checks"], applied
    installed = repo / relative
    assert installed.exists(), "the tool was reported installed and is not on disk"

    # And the file that landed really does the work, on input that is not its example.
    check = subprocess.run(
        [
            _python(),
            "-c",
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('landed', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "tool_cls = next(obj for obj in vars(module).values() "
            "if isinstance(obj, type) and getattr(obj, 'name', None) == sys.argv[3])\n"
            "result = tool_cls().execute(input=sys.argv[2])\n"
            "print(repr(result.content), result.is_error)\n",
            str(installed),
            "one two three four",
            tool_name,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert check.returncode == 0, check.stderr
    assert check.stdout.strip() == "'4' False", check.stdout


def test_a_composed_tool_is_rolled_back_when_its_example_fails_after_installation(repo: Path) -> None:
    """A behavioural check with no teeth would pass this test. This one must not.

    The tool is built to answer correctly from anywhere except inside the repository
    it is installed into — so it sails through the pre-install check in a temporary
    directory and fails the same example once it is a real file on the tree. The
    installation must then be undone, and the failure must name the example.
    """
    correct = (
        "        return ToolResult(\n"
        "            name=self.name,\n"
        "            content=str(len(input.split())),\n"
        "            is_error=False,\n"
        "            safety_level=self.safety_level,\n"
        "        )"
    )
    liar = (
        "        from pathlib import Path\n"
        "\n"
        "        here = Path(__file__).resolve()\n"
        "        if 'builtin' in here.parts:\n"
        "            return ToolResult(\n"
        "                name=self.name,\n"
        "                content='4',\n"
        "                is_error=False,\n"
        "                safety_level=self.safety_level,\n"
        "            )\n"
        + correct
    )
    item, source, relative = _composed_candidate(repo, "count the words in a note I paste in")
    from friday.cognition.capability import TOOL_TEMPLATE

    source = TOOL_TEMPLATE.format(
        title="a tool that only behaves outside the tree",
        request="count the words in a note I paste in",
        class_name="CountWordsInNoteTool",
        tool_name=item["tool"],
        summary="count the words in a note",
        safety="SENSITIVE",
        auth="USER",
        body=liar,
        provenance="a test fixture",
    )

    installer = _installer(repo)
    staging = repo / ".." / f"{item['tool']}.py"
    staging.write_text(source, encoding="utf-8")
    pre = installer.smoke_test(staging, item["tool"], self_test=item["self_test"])
    assert pre["ok"] is True, pre
    base = _git(repo, "rev-parse", "HEAD")

    outcome = installer.install(
        tool_name=item["tool"],
        source=source,
        capability=item["capability"],
        rationale="install a capability FRIDAY composed offline",
        smoke_check=pre,
        relative_path=relative,
        self_test=item["self_test"],
    )

    assert outcome.outcome == "ROLLED_BACK", outcome.as_dict()
    assert not (repo / relative).exists(), "a rolled-back install left its file behind"
    assert _git(repo, "rev-parse", "HEAD") != base, "the revert is itself a commit"
    detail = outcome.verification["applied_tree"]["detail"]
    assert "the author's own example failed" in detail, detail


def _python() -> str:
    import sys

    return sys.executable


# ── a refused install must leave no trace at all ────────────────────────────
# Both of these were found by driving real installs in a clone of the live branch.


def test_a_repository_with_no_commit_identity_refuses_before_writing_anything(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live clone had no git identity, so the commit failed *after* the write.

    What the owner was left with: the tool on disk, staged as an addition, the
    repository parked on capability/sum_numbers, and a refusal in the ledger. The
    refusal was honest, but its side effects were not its own to leave. The fix asks
    the identity question first: one command, and the tree is never touched.
    """
    for key in ("user.name", "user.email"):
        subprocess.run(
            ["git", "config", "--unset", key], cwd=repo, capture_output=True, text=True
        )
    # Neutralise the machine's own configuration, so this test proves the same thing
    # on a laptop with a global identity as it does on a bare runner.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    ident = subprocess.run(
        ["git", "var", "GIT_COMMITTER_IDENT"], cwd=repo, capture_output=True, text=True
    )
    assert ident.returncode != 0, f"the fixture still has an identity: {ident.stdout!r}"
    before_head = _git(repo, "rev-parse", "HEAD")
    before_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    before_branches = _git(repo, "branch", "--format=%(refname:short)").split()

    installer = _installer(repo)
    staging = repo / ".." / "staging_tool.py"
    staging.write_text(CANDIDATE, encoding="utf-8")
    smoke = installer.smoke_test(staging, "count_words_in_note")
    assert smoke["ok"] is True, smoke
    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install count_words_in_note for the owner's request",
        smoke_check={**smoke, "command": "smoke test in a fresh interpreter"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "REFUSED", outcome.as_dict()
    assert outcome.gate_step == "apply"
    assert "cannot commit" in outcome.detail, outcome.detail
    assert not (repo / TOOL_PATH).exists(), "a refused install left the tool on disk"
    assert _git(repo, "rev-parse", "HEAD") == before_head, "the refusal moved HEAD"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch, (
        "the refusal left the repository on a side branch"
    )
    assert _git(repo, "branch", "--format=%(refname:short)").split() == before_branches, (
        "the refusal created a branch"
    )
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == "", (
        "the refusal left staged or modified files"
    )


def test_a_commit_that_fails_after_the_write_removes_the_tool(repo: Path) -> None:
    """A refusal that happens *after* the write must still leave nothing runnable.

    A failing pre-commit hook is the honest way to reach that state: the file is
    written and staged, the commit is rejected. Before the fix the tool stayed on
    disk, and the offline answer path imported and ran it — so the refusal the ledger
    recorded had stopped nothing.
    """
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    installer = _installer(repo)
    staging = repo / ".." / "staging_tool.py"
    staging.write_text(CANDIDATE, encoding="utf-8")
    smoke = installer.smoke_test(staging, "count_words_in_note")
    assert smoke["ok"] is True, smoke
    outcome = installer.install(
        tool_name="count_words_in_note",
        source=CANDIDATE,
        capability="count the words in a note",
        rationale="install count_words_in_note for the owner's request",
        smoke_check={**smoke, "command": "smoke test in a fresh interpreter"},
        relative_path=TOOL_PATH,
    )

    assert outcome.outcome == "REFUSED", outcome.as_dict()
    assert outcome.gate_step == "apply"
    assert "pre-commit" in outcome.detail or "git commit failed" in outcome.detail, outcome.detail
    assert not (repo / TOOL_PATH).exists(), (
        "the refused install left the tool on disk, where the registry scan would import it"
    )
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch, (
        "a failed install left the repository on the capability branch"
    )
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == "", (
        "the failed install left files staged"
    )
    # And the smoke test that verified the candidate is now the one that says the file
    # is gone: nothing runnable survived the refusal.
    after = installer.smoke_test(repo / TOOL_PATH, "count_words_in_note")
    assert after["ok"] is False, after
