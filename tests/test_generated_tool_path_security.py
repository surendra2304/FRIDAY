"""User-facing self-development path and filesystem-boundary regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from friday.cognition.capability import CapabilityResolver
from friday.cognition.installation import CapabilityInstaller, InstallOutcome
from friday.core.types import Message, Role
from friday.tools.builtin.self_development import SelfDevelopTool


class ScriptedOfflineProvider:
    """Return a local plan and implementation without making a network request."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages: list[Message], **_: Any) -> Message:
        self.calls += 1
        system_prompt = messages[0].content
        if "You break an owner's request into steps" in system_prompt:
            content = json.dumps(
                {
                    "steps": [
                        {
                            "intent": "count the words in a note",
                            "tool": None,
                            "arguments": {},
                        }
                    ]
                }
            )
        else:
            content = '''        count = len((input or "").split())
        return ToolResult(
            name=self.name,
            content=str(count),
            is_error=False,
            safety_level=self.safety_level,
        )'''
        return Message(role=Role.ASSISTANT, content=content)


class PendingInstaller:
    """Capture the verified proposal and stop before any repository write."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def install(self, **kwargs: Any) -> InstallOutcome:
        self.kwargs = kwargs
        return InstallOutcome(
            tool=kwargs["tool_name"],
            capability=kwargs["capability"],
            path=kwargs["relative_path"],
            gate_step="authority",
            outcome="AWAITING_MANDATE",
            detail="offline test stopped at the owner-authority gate",
        )


class NeverCalledProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *_: Any, **__: Any) -> Message:
        self.calls += 1
        raise AssertionError("an invalid target path must be rejected before planning")


def test_self_develop_user_path_uses_module_stem_and_stays_offline(tmp_path: Path) -> None:
    provider = ScriptedOfflineProvider()
    installer = PendingInstaller()
    resolver = CapabilityResolver(
        llm=provider,
        repository_root=tmp_path,
        installer=installer,
    )

    result = SelfDevelopTool(resolver=resolver).execute(
        request="count the words in a note I paste in",
        target_path="src/friday/tools/builtin/note_word_count.py",
    )

    assert provider.calls >= 2, "the local planner and author were not exercised"
    assert result.is_error is True, "a candidate waiting on authority is not installed success"
    assert installer.kwargs is not None
    assert installer.kwargs["tool_name"] == "note_word_count"
    assert installer.kwargs["relative_path"] == "src/friday/tools/builtin/note_word_count.py"
    candidate = result.metadata["synthesised"][0]
    assert candidate["tool"] == "note_word_count"
    assert candidate["installation"]["outcome"] == "AWAITING_MANDATE"
    assert not (tmp_path / installer.kwargs["relative_path"]).exists()


@pytest.mark.parametrize(
    "target_path",
    [
        "src/friday/tools/builtin/../../../../../outside.py",
        "../outside.py",
        "/tmp/outside.py",
        r"src\friday\tools\builtin\outside.py",
        "src/friday/tools/builtin/not-a-module.py",
        "src/friday/tools/other.py",
    ],
)
def test_self_develop_refuses_unsafe_target_paths_before_planning(
    tmp_path: Path, target_path: str
) -> None:
    provider = NeverCalledProvider()
    installer = PendingInstaller()
    resolver = CapabilityResolver(
        llm=provider,
        repository_root=tmp_path,
        installer=installer,
    )

    result = SelfDevelopTool(resolver=resolver).execute(
        request="count the words in a note I paste in",
        target_path=target_path,
    )

    assert result.is_error is True
    assert "Rejected target_path" in result.content
    assert provider.calls == 0
    assert installer.kwargs is None
    assert result.metadata["synthesised"] == []


def test_capability_installer_has_its_own_path_boundary(tmp_path: Path, monkeypatch) -> None:
    installer = CapabilityInstaller(tmp_path, gate=object())
    monkeypatch.setattr(
        installer,
        "_gate_or_build",
        lambda: pytest.fail("an unsafe target must be refused before building the gate"),
    )

    outcome = installer.install(
        tool_name="outside",
        source="not written",
        capability="a tool",
        rationale="test path boundary",
        smoke_check={"ok": True, "command": "offline test"},
        relative_path="src/friday/tools/builtin/../../../../../outside.py",
    )

    assert outcome.outcome == "REFUSED"
    assert outcome.gate_step == "propose"
    assert "parent-directory traversal" in outcome.detail
    assert not (tmp_path.parent / "outside.py").exists()
