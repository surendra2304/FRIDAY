"""Regression tests for the filesystem policy, the directive authorization gate
and the git repository guard.

These pin three defects that were reproduced against the running agent rather
than reasoned about:

1. The file tools disagreed about what they could touch. ``read_file`` and
   ``list_dir`` were confined to the working directory; ``file_operations``,
   ``write_code_file`` and ``replace_file_content`` were not confined at all,
   so a relative ``../`` traversal in the write path created files outside the
   workspace while the read path refused the same location. Writing into
   FRIDAY's own package had no guard whatsoever.

2. Direct desktop directives ("email this to X", "whatsapp Y") reached the
   same effects as the SENSITIVE ``send_email`` / ``send_whatsapp_message``
   tools while bypassing the registry, the capability check and the audit
   trail - and the reply still asserted "Scoped approval confirmed."

3. The git tools ran in ``os.getcwd()`` when the model did not name a
   directory, so "create a branch" issued while FRIDAY was launched from its
   own checkout silently moved FRIDAY's own HEAD.
"""

import os
import subprocess
from pathlib import Path

import pytest

from friday.core.types import SafetyLevel
from friday.security.workspace_policy import PathPolicyError, WorkspacePolicy
from friday.tools.builtin.dev_tools import (
    CreateGitBranchTool,
    ReplaceFileContentTool,
    WriteCodeFileTool,
)
from friday.tools.builtin.file_and_command import FileOperationsTool
from friday.tools.builtin.file_listing import FileListingTool
from friday.tools.builtin.file_reader import FileReaderTool
from friday.tools.builtin.git_tools import GitCommitTool, GitPushTool, GitStatusTool


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A working directory of its own, outside the repository checkout."""
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "inside.txt").write_text("hello", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.chdir(work)
    return work, outside


@pytest.fixture()
def policy(workspace):
    work, _ = workspace
    # Build a policy directly so the test does not depend on the cached
    # process-wide instance, and pin the roots to this workspace.
    return WorkspacePolicy(roots=[work], include_defaults=False)


def _fresh_policy(monkeypatch, work):
    """Make the shared policy resolve against *work* for the duration of a test."""
    import friday.security.workspace_policy as wp

    monkeypatch.setattr(wp, "_SHARED", WorkspacePolicy(roots=[work], include_defaults=False), raising=False)
    return wp.shared_policy()


# ---------------------------------------------------------------------------
# 1. the path policy itself
# ---------------------------------------------------------------------------
def test_policy_allows_inside_both_spellings(workspace, policy):
    work, _ = workspace
    assert policy.resolve_for_read("inside.txt") == (work / "inside.txt").resolve()
    assert policy.resolve_for_read(str(work / "inside.txt")) == (work / "inside.txt").resolve()
    assert policy.resolve_for_write("new.txt") == (work / "new.txt").resolve()


def test_policy_refuses_traversal_and_outside(workspace, policy):
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("../outside.txt")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_write("../escaped.txt")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("/etc/hostname")


def test_policy_refuses_credentials_files(workspace, policy):
    (Path.cwd() / ".env").write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read(".env")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_write(".env")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_write("server.pem")


def test_policy_refuses_windows_style_paths_on_posix(workspace, policy):
    if os.name == "nt":  # pragma: no cover - POSIX-specific assertion
        pytest.skip("POSIX-specific")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("C:\\Windows\\system32\\cmd.exe")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("\\Windows\\system32\\cmd.exe")


def test_policy_refuses_self_modification(tmp_path):
    protected = tmp_path / "src" / "friday"
    protected.mkdir(parents=True)
    policy = WorkspacePolicy(roots=[tmp_path], protected_roots=[protected])
    with pytest.raises(PathPolicyError):
        policy.resolve_for_write(protected / "agent.py")
    # ...and permits it once the operator opts in.
    permissive = WorkspacePolicy(
        roots=[tmp_path], protected_roots=[protected], allow_self_modification=True,
        include_defaults=False,
    )
    assert permissive.resolve_for_write(protected / "agent.py")


# ---------------------------------------------------------------------------
# 2. the tools obey the policy
# ---------------------------------------------------------------------------
def test_write_tools_refuse_traversal(workspace, monkeypatch):
    work, _ = workspace
    _fresh_policy(monkeypatch, work)

    for tool, kwargs in (
        (FileOperationsTool(), {"path": "../escaped.txt", "action": "write", "content": "x"}),
        (WriteCodeFileTool(), {"filepath": "../escaped.py", "code": "x"}),
    ):
        result = tool.execute(**kwargs)
        assert result.is_error, f"{tool.name} accepted a traversal"
        assert "Security Error" in result.content

    assert not (work.parent / "escaped.txt").exists()
    assert not (work.parent / "escaped.py").exists()


def test_write_tools_refuse_outside_absolute_path(workspace, monkeypatch):
    work, outside = workspace
    _fresh_policy(monkeypatch, work)

    result = FileOperationsTool().execute(
        path=str(outside), action="write", content="overwritten"
    )
    assert result.is_error
    assert outside.read_text(encoding="utf-8") == "secret"

    result = WriteCodeFileTool().execute(filepath=str(outside), code="overwritten")
    assert result.is_error
    assert outside.read_text(encoding="utf-8") == "secret"


def test_read_and_write_agree_on_absolute_paths(workspace, monkeypatch):
    """The regression that made 'write then read back' fail at step two."""
    work, _ = workspace
    _fresh_policy(monkeypatch, work)
    target = work / "note.txt"

    written = FileOperationsTool().execute(
        path=str(target), action="write", content="remember this"
    )
    assert not written.is_error, written.content

    read = FileReaderTool().execute(path=str(target))
    assert not read.is_error, read.content
    assert "remember this" in read.content

    listed = FileListingTool().execute(path=str(work))
    assert not listed.is_error, listed.content
    assert "note.txt" in listed.content


def test_tools_refuse_to_rewrite_fridays_own_source(tmp_path, monkeypatch):
    source = tmp_path / "src" / "friday"
    source.mkdir(parents=True)
    victim = source / "agent.py"
    victim.write_text("# original\n", encoding="utf-8")

    import friday.security.workspace_policy as wp

    monkeypatch.setattr(
        wp,
        "_SHARED",
        WorkspacePolicy(roots=[tmp_path], protected_roots=[source], include_defaults=False),
        raising=False,
    )
    monkeypatch.chdir(tmp_path)

    for tool, kwargs in (
        (WriteCodeFileTool(), {"filepath": str(victim), "code": "# pwned\n"}),
        (
            ReplaceFileContentTool(),
            {"filepath": str(victim), "old_text": "# original", "new_text": "# pwned"},
        ),
        (
            FileOperationsTool(),
            {"path": str(victim), "action": "write", "content": "# pwned\n"},
        ),
    ):
        result = tool.execute(**kwargs)
        assert result.is_error, f"{tool.name} rewrote FRIDAY's own source"
        assert "Security Error" in result.content

    assert victim.read_text(encoding="utf-8") == "# original\n"


def test_read_tools_still_refuse_traversal(workspace, monkeypatch):
    work, _ = workspace
    _fresh_policy(monkeypatch, work)
    for tool in (FileReaderTool(), FileListingTool()):
        result = tool.execute(path="../")
        assert result.is_error
        assert "Security Error" in result.content


# ---------------------------------------------------------------------------
# 3. the direct-desktop authorization gate
# ---------------------------------------------------------------------------
def _directive(monkeypatch, decisions, request_log):
    """Run one email directive through the device layer with a stub authorizer."""
    from friday.core.types import (
        AuthorizationDecision,
        AuthorizationRequest,
        AuthorizationResponse,
    )
    from friday.devices import windows_friday as wf

    class Recorder:
        def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
            request_log.append(request)
            approved = decisions.pop(0) if decisions else False
            return AuthorizationResponse(
                decision=(
                    AuthorizationDecision.APPROVED if approved else AuthorizationDecision.DENIED
                ),
                reason="test-authorizer",
            )

    class StubOutcome:
        sent = False
        detail = "stub did not send"
        provider = "smtp"

    monkeypatch.setattr(
        wf.WindowsFridayController, "open_gmail", lambda self, **kw: StubOutcome(), raising=True
    )
    handled, reply, meta = wf.windows_friday.handle_directive(
        "email the report to a@b.com", authorizer=Recorder()
    )
    return handled, reply, meta


def test_email_directive_is_refused_without_an_authorizer(monkeypatch):
    from friday.devices import windows_friday as wf

    called = {"sent": False}
    monkeypatch.setattr(
        wf.WindowsFridayController,
        "open_gmail",
        lambda self, **kw: called.__setitem__("sent", True),
    )
    handled, reply, meta = wf.windows_friday.handle_directive("email the report to a@b.com")

    assert handled
    assert called["sent"] is False, "an unapproved email reached the device layer"
    assert meta.get("authorization") == "DENIED"
    assert "refused" in reply.lower()


def test_email_directive_asks_the_authorizer_and_reports_the_decision(monkeypatch):
    log = []
    handled, reply, meta = _directive(monkeypatch, [False], log)

    assert handled
    assert [r.tool_name for r in log] == ["send_email"]
    assert log[0].safety_level == SafetyLevel.SENSITIVE
    assert meta.get("authorization") == "DENIED"
    assert "refused" in reply.lower()


def test_email_directive_never_claims_approval_it_did_not_get(monkeypatch):
    """The original text said 'Scoped approval confirmed.' unconditionally."""
    log = []
    _, denied_reply, _ = _directive(monkeypatch, [False], log)
    assert "Scoped approval confirmed" not in denied_reply
    assert "APPROVED" not in denied_reply

    _, approved_reply, meta = _directive(monkeypatch, [True], log)
    assert "Scoped approval confirmed" not in approved_reply
    assert "APPROVED" in approved_reply
    assert meta.get("authorization") != "DENIED"


# ---------------------------------------------------------------------------
# 4. the git repository guard
# ---------------------------------------------------------------------------
def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


def test_git_refuses_to_mutate_fridays_own_repository(tmp_path, monkeypatch):
    """Reproduces the incident: launching from FRIDAY's checkout moved its HEAD."""
    project = tmp_path / "fake_friday"
    (project / "src" / "friday").mkdir(parents=True)
    (project / "src" / "friday" / "__init__.py").write_text("", encoding="utf-8")
    _init_repo(project)

    import friday.security.workspace_policy as wp

    monkeypatch.setattr(
        wp,
        "_SHARED",
        WorkspacePolicy(
            roots=[project], protected_roots=[project / "src" / "friday"], include_defaults=False
        ),
        raising=False,
    )
    monkeypatch.chdir(project)

    before = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project, capture_output=True, text=True
    ).stdout.strip()

    assert CreateGitBranchTool().execute(branch_name="sneaky").is_error
    assert GitCommitTool().execute(message="sneaky").is_error
    assert GitPushTool().execute().is_error

    after = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project, capture_output=True, text=True
    ).stdout.strip()
    assert before == after, "a tool call moved the repository HEAD"
    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=project, capture_output=True, text=True
    ).stdout.split()
    assert "sneaky" not in branches


def test_git_still_works_on_a_repository_the_user_names(tmp_path, monkeypatch):
    project = _init_repo(tmp_path / "myproject")

    import friday.security.workspace_policy as wp

    monkeypatch.setattr(
        wp, "_SHARED", WorkspacePolicy(roots=[tmp_path], include_defaults=False), raising=False
    )

    status = GitStatusTool().execute(cwd=str(project))
    assert not status.is_error, status.content
    assert "nothing to commit" in status.content

    created = CreateGitBranchTool().execute(branch_name="feature-a", cwd=str(project))
    assert not created.is_error, created.content
    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=project, capture_output=True, text=True
    ).stdout.split()
    assert "feature-a" in branches


def test_git_refuses_a_directory_outside_the_workspace(tmp_path, monkeypatch):
    project = _init_repo(tmp_path / "myproject")

    import friday.security.workspace_policy as wp

    monkeypatch.setattr(
        wp, "_SHARED", WorkspacePolicy(roots=[tmp_path / "elsewhere"], include_defaults=False), raising=False
    )

    result = CreateGitBranchTool().execute(branch_name="nope", cwd=str(project))
    assert result.is_error
    assert "Refused" in result.content


# --------------------------------------------------------------- live workspace
def test_policy_follows_the_process_working_directory(tmp_path, monkeypatch):
    """A long-lived FRIDAY must not keep using the directory it started in.

    The policy cached ``roots[0]`` at construction, so after any change of
    working directory - a `cd` tool, a scheduler, a restart from another folder -
    relative paths still resolved against the old workspace. That failed both
    ways: an existing file was refused, and a relative *write* landed in the old
    directory without saying so.
    """
    from friday.security.workspace_policy import WorkspacePolicy

    first = tmp_path / "start"
    second = tmp_path / "later"
    first.mkdir()
    second.mkdir()
    (first / "from_start.txt").write_text("start\n")
    (second / "from_later.txt").write_text("later\n")

    monkeypatch.chdir(first)
    policy = WorkspacePolicy(include_defaults=False, roots=[str(tmp_path)])

    assert policy.base == first.resolve()

    monkeypatch.chdir(second)
    assert policy.base == second.resolve()

    # A relative path resolves against where we are now.
    assert policy.resolve("from_later.txt", must_exist=True) == (second / "from_later.txt").resolve()
    # And the directory we came from is still inside the configured roots when
    # it is named explicitly - the root is not revoked, it is just no longer
    # what an unqualified name means.
    assert policy.resolve(str(first / "from_start.txt"), must_exist=True) == (first / "from_start.txt").resolve()


def test_a_write_after_changing_directory_lands_where_the_user_is(tmp_path, monkeypatch):
    from friday.tools.builtin.dev_tools import WriteCodeFileTool

    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()

    monkeypatch.chdir(here)
    WriteCodeFileTool().execute(filepath="early.txt", code="1")

    monkeypatch.chdir(there)
    WriteCodeFileTool().execute(filepath="late.txt", code="2")

    assert (here / "early.txt").exists()
    assert (there / "late.txt").exists(), "the write landed in the abandoned directory"
    assert not (here / "late.txt").exists()


def test_the_live_directory_is_reported_as_a_root(tmp_path, monkeypatch):
    from friday.security.workspace_policy import WorkspacePolicy

    monkeypatch.chdir(tmp_path)
    policy = WorkspacePolicy(include_defaults=False, roots=["/tmp"])
    assert str(tmp_path.resolve()) in policy.describe()
    assert tmp_path.resolve() in policy.effective_roots()
