"""What FRIDAY answers when its model is unreachable, and what it refuses to claim.

Found by using the thing. The owner said "count the words in this note: the quick
brown fox jumps over the lazy dog" and FRIDAY answered "LLM generation failed. I'm
having trouble connecting to my intelligence core" - while holding a working
word-counting tool it had composed and installed itself, and a planner that could
have found it. That is the failure this file exists to keep fixed, and the tests are
written to run against the *same* machinery the conversation uses: a real tool
registry, the real authorizer, and real tools on disk.

Two halves. The first is that the work gets done, and the answer says where it came
from - the tool, the input it was given, and the output it returned, so the owner can
check the work instead of trusting the sentence. The second is what must not happen:
a request that needs judgement, hardware, or a reviewer must not be dressed up as a
success, and an unreviewed tool must not be run without the owner's consent on
record.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from friday.cognition.offline import (
    answer_without_a_model,
    composed_by_friday,
    consent_for_unreviewed_tool,
    payload_from,
    purity_verdict,
)
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry

REVIEW_KEY = b"offline-fallback-review-key"
MANDATE_KEY = b"offline-fallback-mandate-key"


class _EchoTool(BaseTool):
    """A tool of the kind FRIDAY composes: a function of the text it is given."""

    name = "count_words_in_a_note"
    description = "Count the words in the note."
    safety_level = SafetyLevel.SENSITIVE

    def execute(self, input: str = "", **_: object) -> ToolResult:
        import re

        return ToolResult(
            name=self.name,
            content=str(len(re.findall(r"\S+", input))),
            is_error=False,
            safety_level=self.safety_level,
        )


class _SideEffectTool(BaseTool):
    """Not pure: it can touch the machine, and must never be run unattended."""

    name = "rename_every_file"
    description = "Rename files."
    safety_level = SafetyLevel.SENSITIVE

    def execute(self, input: str = "", **_: object) -> ToolResult:
        import os

        os.getcwd()
        return ToolResult(
            name=self.name, content="done", is_error=False, safety_level=self.safety_level
        )


# ── the payload ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "goal,expected",
    [
        (
            "count the words in this note: the quick brown fox",
            "the quick brown fox",
        ),
        ("reverse the text 'hello world'", "hello world"),
        ('sum the numbers "1 2 3"', "1 2 3"),
        ("count the words", "count the words"),
    ],
)
def test_the_payload_is_the_owner_s_data_not_the_instruction(goal: str, expected: str) -> None:
    """Counting the instruction itself would be a wrong answer, delivered confidently."""
    assert payload_from(goal) == expected


# ── purity, checked by reading the code ───────────────────────────────────────


def test_a_pure_tool_is_recognised_by_reading_its_code() -> None:
    pure, why = purity_verdict(_EchoTool())
    assert pure is True, why
    # Purity and provenance are different facts: this tool is pure, and no part of
    # FRIDAY wrote it, which is a separate reason to refuse it unattended.
    composed, provenance = composed_by_friday(_EchoTool())
    assert composed is False
    assert "does not declare" in provenance


def test_a_tool_that_can_touch_the_machine_is_never_pure() -> None:
    pure, why = purity_verdict(_SideEffectTool())
    assert pure is False
    assert "os." in why, why


def test_a_class_that_lies_about_being_pure_is_still_read() -> None:
    """The check reads source, so a flag cannot buy a pass."""

    class Liar(_SideEffectTool):
        name = "lies_about_purity"
        pure_text_function = True  # a claim, and worth nothing

    pure, why = purity_verdict(Liar())
    assert pure is False, "a purity flag bought a pass"
    assert "os." in why


# ── consent ───────────────────────────────────────────────────────────────────


def test_without_a_mandate_or_autonomous_mode_there_is_no_consent(tmp_path: Path) -> None:
    consent, reason = consent_for_unreviewed_tool("src/friday/tools/builtin/x.py")
    assert consent is False
    assert reason, "a refusal must say why"


def test_a_standing_mandate_covering_the_tool_is_consent(tmp_path: Path, monkeypatch) -> None:
    from friday.cognition.mandate import AutonomyMandate, MandateAuthority, MandateLedger
    import time as _time

    ledger_path = tmp_path / "mandates.json"
    monkeypatch.setenv("FRIDAY_AUTONOMY_KEY", MANDATE_KEY.decode())
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(ledger_path))
    signed = AutonomyMandate(
        issued_by="Surendra",
        scopes=("source_repair",),
        allowed_paths=("src/**",),
        expires_at=_time.time() + 600,
    ).sign(MANDATE_KEY)
    MandateLedger(str(ledger_path)).record_grant(signed)

    consent, reason = consent_for_unreviewed_tool("src/friday/tools/builtin/x.py")
    assert consent is True, reason
    assert "mandate" in reason

    # ...and a path the mandate does not cover is still not consent.
    consent, reason = consent_for_unreviewed_tool("deploy/production.yaml")
    assert consent is False, reason
    assert "mandate" in reason


# ── the whole answer, through a real registry and the real authorizer ─────────


def _registry_with(tool: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


class _DenyingAuthorizer:
    """The default authorizer's answer for a SENSITIVE tool with no confirmation."""

    def authorize(self, request):
        from friday.core.types import AuthorizationDecision, AuthorizationResponse

        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason=(
                f"Safety Block: Tool '{request.tool_name}' requires explicit user confirmation. "
                "No interactive authorizer was configured."
            ),
        )


def test_a_counting_request_is_answered_with_its_own_tool(tmp_path: Path) -> None:
    """The whole point: the work gets done, and the answer shows its evidence."""
    from friday.cognition import capability as capability_module

    (tmp_path / "src/friday/tools/builtin").mkdir(parents=True)
    (tmp_path / "README.md").write_text("scratch\n", encoding="utf-8")
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "o@example.invalid"),
        ("config", "user.name", "Owner"),
        ("add", "-A"),
        ("commit", "-qm", "base"),
    ):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)
    monkeypatch_tools = tmp_path / "src/friday/tools/builtin/count_words_in_a_note.py"
    monkeypatch_tools.write_text(
        "from friday.cognition.offline import _EchoTool  # pragma: no cover\n", encoding="utf-8"
    )
    # The catalogue is what the planner reads; the real class is this file's.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        capability_module.ToolCatalogue, "entries", lambda self: {"count_words_in_a_note": _EchoTool()}
    )

    class _Approving(_DenyingAuthorizer):
        def authorize(self, request):
            from friday.core.types import AuthorizationRequest  # noqa: F401
            from friday.core.types import AuthorizationDecision, AuthorizationResponse

            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="test",
                capability="signed-capability",
            )

    class _CapabilityRegistry(ToolRegistry):
        def execute(self, name, arguments, **kwargs):
            return self.get(name).execute(**arguments)

    registry = _CapabilityRegistry()
    registry.register(_EchoTool())
    try:
        answer = answer_without_a_model(
            "count the words: the quick brown fox jumps over the lazy dog",
            registry=registry,
            repo_root=tmp_path,
            authorizer=_Approving(),
        )
    finally:
        monkeypatch.undo()

    assert answer is not None
    assert answer.success is True, answer.detail
    assert answer.used and answer.used[0]["output"] == "9", answer.used
    assert "9" in answer.spoken
    assert "own tooling" in answer.spoken


def test_a_request_needing_judgement_is_not_dressed_up_as_a_success(tmp_path: Path) -> None:
    """"how are you feeling today?" is conversation. Nothing local answers it."""
    answer = answer_without_a_model("how are you feeling today?", repo_root=tmp_path)
    assert answer is None or answer.success is False


def test_hardware_this_host_does_not_have_is_reported_not_attempted(tmp_path: Path) -> None:
    answer = answer_without_a_model("transcribe my microphone recording", repo_root=tmp_path)
    assert answer is not None
    assert answer.success is False
    assert answer.built == [], "a tool was built for something no tool can supply"


def test_an_unreviewed_tool_is_not_run_without_consent(tmp_path: Path) -> None:
    """Purity is not permission. Without the owner's consent the refusal stands."""
    registry = _registry_with(_EchoTool())
    answer = answer_without_a_model(
        "count the words: one two three",
        registry=registry,
        repo_root=tmp_path,
        authorizer=_DenyingAuthorizer(),
    )

    assert answer is not None
    assert answer.success is False
    assert answer.used, "the attempt must be reported rather than hidden"
    assert answer.used[0]["is_error"] is True
    assert "Authorization Block" in answer.used[0]["output"]


# ── two defects the live run found, pinned so they stay fixed ─────────────────


def test_a_tool_installed_after_the_registry_was_built_is_still_visible(tmp_path: Path) -> None:
    """The registry answered a request while a working tool for it sat on disk.

    Found in the live deployment: the registry is built at start-up, the capability
    was installed minutes later, and `ToolCatalogue.entries()` returned the registry
    *instead of* the scan - so the planner saw 76 tools, missed the 77th, and reported
    that nothing could be carried out. A tool on disk is a tool that exists.
    """
    from friday.cognition.capability import ToolCatalogue

    registry = ToolRegistry()
    registry.register(_EchoTool())

    catalogue = ToolCatalogue(registry)
    names = catalogue.names()

    assert "count_words_in_a_note" in names, "the registry's own tool went missing"
    assert "calculator" in names, "a tool on disk went missing because a registry was supplied"
    assert len(names) > len(registry.list_tools())


def test_a_tool_loaded_under_a_synthetic_module_name_still_has_a_path() -> None:
    """The path is what the mandate is asked about, so it must not be empty by accident.

    Found in the live deployment: a tool installed moments ago is loaded under
    `friday_installed_<name>`, not as `friday.tools.builtin.<name>`, so looking the
    module up by name found nothing and the mandate was asked about "". The tool's own
    file is the honest source for where it is.
    """
    import importlib.util
    import sys
    import tempfile

    from friday.cognition.offline import _tool_path

    source = (
        '"""A tool for the test."""\n\n'
        "from friday.core.types import SafetyLevel, ToolResult\n"
        "from friday.tools.base import BaseTool\n\n\n"
        "class SyntheticTool(BaseTool):\n"
        '    """Synthetic."""\n\n'
        '    name = "synthetic_probe"\n'
        "    safety_level = SafetyLevel.SENSITIVE\n\n"
        "    def execute(self, input: str = '', **_: object) -> ToolResult:\n"
        "        return ToolResult(name=self.name, content=input, safety_level=self.safety_level)\n"
    )
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir) / "repo"
        target = root / "src/friday/tools/builtin/synthetic_probe.py"
        target.parent.mkdir(parents=True)
        target.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("friday_installed_synthetic_probe", target)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["friday_installed_synthetic_probe"] = module  # as the loader does
        spec.loader.exec_module(module)
        try:
            registry = ToolRegistry()
            registry.register(module.SyntheticTool())

            assert _tool_path(registry, "synthetic_probe") == (
                "src/friday/tools/builtin/synthetic_probe.py"
            )
        finally:
            sys.modules.pop("friday_installed_synthetic_probe", None)
