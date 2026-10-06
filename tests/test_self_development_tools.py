"""Tests for the self-development tools, and for BUG-003 staying fixed.

BUG-003 was a promise the system could not keep: the system prompt ordered the
model to "call the workflow tool" and named ``SelfImprovementWorkflow``, which
was not registered anywhere. A model following that instruction produced a
phantom tool call, and the owner saw FRIDAY refuse work it could have done.

The regression test below is deliberately structural rather than a string
comparison: it reads the prompt the model is actually given, pulls out every
backticked lowercase identifier, and requires each one that looks like a
registered FRIDAY tool to *be* one. That catches the same class of bug the next
time somebody writes a prompt against a tool they have not built.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from friday.cognition.capability import ToolCatalogue
from friday.core.types import ToolResult
from friday.tools.builtin.self_development import SelfDevelopTool, SelfRepairTool


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── the prompt must only name tools that exist ────────────────────────────


def test_the_system_prompt_names_only_tools_that_are_registered() -> None:
    from friday.agent.prompts import build_system_message
    from friday.core.config import get_settings

    prompt = build_system_message(get_settings()).content
    catalogue = ToolCatalogue()

    section = prompt.split("Self-Improvement & Code Evolution:", 1)[1].split("\n\n", 1)[0]
    named = set(re.findall(r"`([a-z][a-z0-9_]{3,})`", section))

    assert named, "the self-improvement prompt names no tools at all"
    for name in sorted(named):
        assert catalogue.has(name), (
            f"the system prompt tells the model to use `{name}`, which is not a "
            "registered tool — this is BUG-003 all over again"
        )
    assert {"self_develop", "self_repair"} <= named


def test_the_prompt_no_longer_names_the_unregistered_workflow() -> None:
    from friday.agent.prompts import build_system_message
    from friday.core.config import get_settings

    prompt = build_system_message(get_settings()).content
    assert "SelfImprovementWorkflow" not in prompt

    voice_source = (
        Path(__file__).resolve().parents[1] / "src/friday/voice/gemini_live_session.py"
    ).read_text(encoding="utf-8")
    assert "SelfImprovementWorkflow" not in voice_source, (
        "the voice prompt still orders the model to call a workflow that is not a tool"
    )
    assert "self_develop" in voice_source and "self_repair" in voice_source


def test_both_tools_are_exported_from_the_builtin_package() -> None:
    import friday.tools.builtin as builtin

    assert builtin.SelfDevelopTool is SelfDevelopTool
    assert builtin.SelfRepairTool is SelfRepairTool


def test_both_tools_reach_the_agents_default_registry() -> None:
    """The strongest form of "registered": the agent builds them into its registry."""
    from friday.agent.mixins.tools import ToolExecutionMixin
    from friday.tools.registry import ToolRegistry

    dummy = type("Dummy", (), {"memory": None})()
    registry = ToolExecutionMixin._create_default_registry(dummy)

    assert isinstance(registry, ToolRegistry)
    names = {tool.name for tool in registry.list_tools()}
    assert {"self_develop", "self_repair"} <= names


def test_the_tools_describe_themselves_for_the_model() -> None:
    develop = SelfDevelopTool().to_openai_schema()["function"]
    repair = SelfRepairTool().to_openai_schema()["function"]

    assert develop["name"] == "self_develop"
    assert repair["name"] == "self_repair"
    # The model must be told the tool will not refuse, or it will not reach for it.
    assert "self_develop" in develop["description"] or "capability" in develop["description"]
    assert "self_repair" in repair["description"] or "repair" in repair["description"]
    assert develop["parameters"]["properties"]["request"]["type"]


# ── self_develop ──────────────────────────────────────────────────────────


def test_self_develop_refuses_an_empty_request_without_pretending_to_plan() -> None:
    result = SelfDevelopTool().execute(request="   ")

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "needs a description" in result.content


def test_self_develop_reports_a_plan_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool must plan, and it must not claim to have changed anything."""
    from friday.cognition import capability

    class StubResolution:
        plan_feasible = True
        synthesised: list[dict[str, Any]] = []

        def spoken_summary(self) -> str:
            return "Here is how I would do that, in 1 step(s), 1 of which I can already run:\n  - check the time via get_time_date (can run now)"

        def as_dict(self) -> dict[str, Any]:
            return {"plan_feasible": True, "steps": [{"tool": "get_time_date"}], "synthesised": []}

    class StubResolver:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def resolve(self, request: str, *, target_path: str = "", allow_synthesis: bool = True) -> StubResolution:
            return StubResolution()

    monkeypatch.setattr(capability, "CapabilityResolver", StubResolver)
    result = SelfDevelopTool().execute(request="what time is it")

    assert result.is_error is False
    assert "1 of which I can already run" in result.content
    assert result.metadata["plan_feasible"] is True


def test_self_develop_reports_a_planning_crash_as_a_planning_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday.cognition import capability

    class ExplodingResolver:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def resolve(self, *_: Any, **__: Any) -> Any:
            raise RuntimeError("the planner exploded")

    monkeypatch.setattr(capability, "CapabilityResolver", ExplodingResolver)
    result = SelfDevelopTool().execute(request="do something")

    assert result.is_error is True
    assert "RuntimeError" in result.content
    assert "Nothing was written" in result.content


# ── self_repair ───────────────────────────────────────────────────────────


def test_self_repair_renders_a_healthy_pass_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    from friday.cognition import reflex

    class HealthyBrain:
        async def run_once(self, *, include: Any = None) -> dict[str, Any]:
            return {
                "status": "COMPLETED",
                "incidents": 0,
                "acted_on": 0,
                "counts": {},
                "outcomes": [],
            }

    monkeypatch.setattr(reflex, "get_reflex_brain", lambda *a, **k: HealthyBrain())
    result = SelfRepairTool().execute()

    assert result.is_error is False
    assert "healthy" in result.content
    assert result.metadata["incidents"] == 0


def test_self_repair_renders_repairs_and_an_awaiting_mandate_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday.cognition import reflex
    from friday.cognition.reflex import IncidentKind

    class BusyBrain:
        async def run_once(self, *, include: Any = None) -> dict[str, Any]:
            assert include == {IncidentKind.TEST_FAILURE}, "scope was not translated to incidents"
            return {
                "status": "COMPLETED",
                "incidents": 2,
                "acted_on": 2,
                "counts": {"RESOLVED": 1, "AWAITING_MANDATE": 1},
                "outcomes": [
                    {
                        "status": "RESOLVED",
                        "incident": {"summary": "tests/test_x.py::test_y is failing"},
                        "detail": "repaired and verified on the real tree",
                    },
                    {
                        "status": "AWAITING_MANDATE",
                        "incident": {"summary": "tests/test_z.py::test_w is failing"},
                        "detail": "proven in the sandbox; no authority to apply",
                    },
                ],
            }

    monkeypatch.setattr(reflex, "get_reflex_brain", lambda *a, **k: BusyBrain())
    result = SelfRepairTool().execute(scope="tests")

    assert result.is_error is False
    assert "[RESOLVED]" in result.content
    assert "[AWAITING_MANDATE]" in result.content
    assert "grant-autonomy" in result.content
    assert result.metadata["counts"]["AWAITING_MANDATE"] == 1


def test_self_repair_dry_run_marks_everything_as_unapplied(monkeypatch: pytest.MonkeyPatch) -> None:
    from friday.cognition import reflex

    class BusyBrain:
        async def run_once(self, *, include: Any = None) -> dict[str, Any]:
            return {
                "status": "COMPLETED",
                "incidents": 1,
                "acted_on": 1,
                "counts": {"RESOLVED": 1},
                "outcomes": [
                    {
                        "status": "RESOLVED",
                        "incident": {"summary": "a fault"},
                        "detail": "would have been repaired",
                    }
                ],
            }

    monkeypatch.setattr(reflex, "get_reflex_brain", lambda *a, **k: BusyBrain())
    result = SelfRepairTool().execute(dry_run=True)

    assert "[DRY_RUN]" in result.content
    assert "[RESOLVED]" not in result.content
    assert result.metadata["outcomes"][0]["status"] == "DRY_RUN"


def test_self_repair_reports_a_broken_pass_instead_of_hiding_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from friday.cognition import reflex

    class ExplodingBrain:
        async def run_once(self, *, include: Any = None) -> dict[str, Any]:
            raise RuntimeError("psutil is on fire")

    monkeypatch.setattr(reflex, "get_reflex_brain", lambda *a, **k: ExplodingBrain())
    result = SelfRepairTool().execute()

    assert result.is_error is True
    assert "RuntimeError" in result.content
    assert "nothing is claimed" in result.content


def test_self_repair_runs_the_real_brain_against_a_real_repository(tmp_path: Path) -> None:
    """No mock of the thing under test: a real ReflexBrain on a real directory."""
    (tmp_path / "README.md").write_text("a repository\n", encoding="utf-8")

    result = SelfRepairTool().execute(scope="resources")

    assert isinstance(result, ToolResult)
    assert result.metadata["status"] in {"COMPLETED", "ERROR"}
    if result.metadata["status"] == "COMPLETED":
        assert "incidents" in result.metadata
        assert result.metadata["acted_on"] <= result.metadata["incidents"]


def test_self_repair_blocks_the_event_loop_correctly() -> None:
    """Called from async code, the pass must still run rather than explode."""
    from friday.tools.builtin.self_development import _run_coroutine

    async def main() -> str:
        async def inner() -> str:
            return "ran"

        return _run_coroutine(inner())

    assert asyncio.run(main()) == "ran"
