"""Tests for the unattended repair loop — the caller Phase F2 was missing.

``tests/test_repair_trigger.py`` covers what the trigger does and, mostly, what
it refuses. Nothing covered the gap that made it unreachable: nothing in the
running service ever called it. So these tests are about the caller, and about the
one property a scheduled job absolutely cannot get wrong.

That property is silence. A loop that checked nothing and a loop that checked
everything and found nothing produce the same empty result. Scheduled on an
interval and read by someone looking for good news, "no findings" is the answer
they most want to believe. So this file pins the unconfigured case hard: it must
say ``NOT_CONFIGURED``, name the environment key that is missing, and never be
readable as a clean pass.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from friday.autonomous.repair_loop import (
    AutonomousRepairLoop,
    LoopConfig,
    repair_loop,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "friday"
LOOP = SRC / "autonomous" / "repair_loop.py"
SERVER = SRC / "api" / "server.py"

_LOOP_ENV = (
    "FRIDAY_SELF_REPAIR_TRIGGER_ENABLED",
    "FRIDAY_SELF_REPAIR_WATCHLIST",
    "FRIDAY_SELF_REPAIR_GATE_URL",
    "FRIDAY_SELF_REPAIR_GATE_KEY",
    "FRIDAY_SELF_REPAIR_REVIEW_KEY",
    "FRIDAY_UNIVERSE_ROOT",
    "FRIDAY_SELF_REPAIR_REVIEWER_STATE",
    "FRIDAY_SELF_REPAIR_TRIGGER_INTERVAL_SECONDS",
)


@pytest.fixture(autouse=True)
def _clear_loop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured loop on a developer's machine must not make these lie."""
    for name in _LOOP_ENV:
        monkeypatch.delenv(name, raising=False)


def _configured(**overrides: Any) -> LoopConfig:
    base = {
        "enabled": True,
        "watchlist_path": "w.json",
        "gate_url": "http://127.0.0.1:1",
        "gate_key": "control",
        "review_key": "review",
    }
    base.update(overrides)
    return LoopConfig(**base)


def _write_watchlist(tmp_path: Path, specs: list[dict[str, Any]]) -> str:
    path = tmp_path / "watchlist.json"
    path.write_text(json.dumps(specs), encoding="utf-8")
    return str(path)


def _one_spec(repo: str = "/tmp/target") -> dict[str, Any]:
    return {
        "name": "describe-double-scales",
        "repo_path": repo,
        "base_commit": "abc",
        "branch": "repair/x",
        "target_file": "percent_change.py",
        "original_snippet": "old\n",
        "replacement_snippet": "new\n",
        "rationale": "double scales",
        "test_command": "pytest -q",
    }


# ── the silent-loop trap ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_loop_with_nothing_configured_does_not_claim_a_pass() -> None:
    """The headline. Unconfigured must never be readable as 'nothing wrong'."""
    result = await AutonomousRepairLoop(LoopConfig()).run_once()

    assert result["status"] == "NOT_CONFIGURED"
    assert result["missing"], "it must name what is missing, not merely refuse"
    assert result["outcomes"] if "outcomes" in result else True
    assert "COMPLETED" not in json.dumps(result), "an unconfigured pass is not a pass"


@pytest.mark.asyncio
async def test_every_missing_key_is_named_by_its_environment_variable() -> None:
    config = LoopConfig()
    gaps = config.missing()

    for name in (
        "FRIDAY_SELF_REPAIR_TRIGGER_ENABLED",
        "FRIDAY_SELF_REPAIR_WATCHLIST",
        "FRIDAY_SELF_REPAIR_GATE_URL",
        "FRIDAY_SELF_REPAIR_GATE_KEY",
        "FRIDAY_SELF_REPAIR_REVIEW_KEY",
    ):
        assert name in gaps, f"{name} missing is not reported, so it cannot be set"


@pytest.mark.asyncio
async def test_a_configured_loop_reports_no_missing_keys() -> None:
    assert _configured().missing() == []


@pytest.mark.asyncio
async def test_a_loop_that_cannot_read_its_watchlist_says_error_not_success() -> None:
    config = _configured(watchlist_path=str(Path("/tmp/definitely-not-here-zzz.json")))
    result = await AutonomousRepairLoop(config).run_once()

    assert result["status"] == "ERROR"
    assert "COMPLETED" not in json.dumps(result)


@pytest.mark.asyncio
async def test_an_empty_watchlist_is_refused_rather_than_reported_as_a_clean_sweep() -> None:
    """Zero specs is a misconfiguration, and it reads exactly like good news."""
    tmp_path = Path(__import__("tempfile").mkdtemp(prefix="f2-empty-"))
    config = _configured(watchlist_path=_write_watchlist(tmp_path, []))
    result = await AutonomousRepairLoop(config).run_once()

    # A real Forge/Sentinel run is out of reach in a unit test, so the pass may
    # fail to build. What must never happen is a COMPLETED pass over nothing.
    assert result["status"] != "COMPLETED"
    assert result["status"] in {"NOT_CONFIGURED", "ERROR"}


# ── it is reachable in the running service ───────────────────────────────


def test_the_lifespan_starts_the_repair_loop() -> None:
    """Without a task in the lifespan, the loop is the demo it was before."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))

    lifespan = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"
    )
    created = [
        ast.unparse(kw.value)
        for call in ast.walk(lifespan)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "create_task"
        for kw in call.keywords
        if kw.arg == "name"
    ]
    assert any("repair" in name for name in created), (
        f"the lifespan starts no repair task; it starts {created}"
    )


def test_the_repair_loop_task_is_cancelled_on_shutdown() -> None:
    """A task that outlives shutdown is a repair pass firing into a dead process.

    Shutdown cancels through a tuple rather than naming each task, so this reads
    the AST for a loop whose body calls ``cancel`` and checks the repair task is
    actually in what it iterates. A grep for ``repair_task.cancel()`` would fail
    against correct code and pass against a stray call.
    """
    source = SERVER.read_text(encoding="utf-8")
    assert "friday-autonomous-repair" in source

    tree = ast.parse(source)
    cancel_loops = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.For)
        and any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "cancel"
            for inner in ast.walk(node)
        )
    ]
    cancelled = {
        name
        for loop in cancel_loops
        for elt in ast.walk(loop.iter)
        if isinstance(elt, ast.Name)
        for name in [elt.id]
    }
    assert "repair_task" in cancelled, (
        f"the repair task is created but never cancelled; cancelled tasks: {sorted(cancelled)}"
    )


def test_the_status_route_is_not_shadowed_by_the_patch_id_catch_all() -> None:
    """FastAPI matches in registration order; a literal after a catch-all is dead."""
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))

    # Routes live in a function's decorator_list, not in the route call itself.
    paths: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if (
                isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Attribute)
                and deco.func.attr in {"get", "post"}
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
            ):
                paths.append(str(deco.args[0].value))
    order = {p: i for i, p in enumerate(paths)}

    autonomous = "/api/self-repair/autonomous"
    catch_all = "/api/self-repair/{patch_id}"
    assert autonomous in order, "the status route is missing"
    assert catch_all in order, "the catch-all is missing, so this test is not testing anything"
    assert order[autonomous] < order[catch_all], (
        f"{autonomous} is registered after {catch_all} and will be read as a patch id"
    )


def test_the_module_exposes_one_loop_instance() -> None:
    """Endpoints and the lifespan task must read the same object, not two."""
    from friday.api import server

    assert server.repair_loop is repair_loop


# ── it cannot approve or apply ───────────────────────────────────────────


def test_the_loop_has_no_apply_or_approve_of_its_own() -> None:
    """The owner gate is the only thing that writes. Enforced by absence."""
    tree = ast.parse(LOOP.read_text(encoding="utf-8"))

    calls = {
        ast.unparse(n.func)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    for forbidden in ("apply", "rollback", "record_owner_decision"):
        assert not any(call.endswith(f".{forbidden}") for call in calls), (
            f"the loop calls {forbidden}, which belongs to the owner and not to it"
        )


def test_the_status_endpoint_is_read_only_and_open() -> None:
    """An owner deciding whether to trust the loop should not need a key to look."""
    source = SERVER.read_text(encoding="utf-8")
    body = source.split("async def autonomous_repair_status", 1)[1].split("@app.", 1)[0]
    assert "_require_control_access" not in body, "the status endpoint became gated"
    assert "repair_loop.status()" in body


def test_running_a_pass_on_demand_stays_behind_control_access() -> None:
    source = SERVER.read_text(encoding="utf-8")
    body = source.split("async def run_autonomous_repair_now", 1)[1].split("@app.", 1)[0]
    assert "_require_control_access" in body, "a pass can be triggered by anyone"


# ── the review key is not the control key ────────────────────────────────


def test_the_reviewer_signs_with_the_review_key_not_the_control_key() -> None:
    """Signing with the control key makes every review REFUSED, always.

    Found by running the loop for real: the patch filed fine and the review came
    back refused, which reads like Sentinel rejecting the fix rather than a key
    that was never going to verify.
    """
    source = LOOP.read_text(encoding="utf-8")
    assert "signing_key=self._config.review_key" in source
    assert "signing_key=self._config.gate_key" not in source


def test_the_two_keys_are_configured_independently() -> None:
    config = _configured(gate_key="control", review_key="review")
    assert config.gate_key != config.review_key

    only_control = LoopConfig(enabled=True, watchlist_path="w", gate_url="u", gate_key="k")
    assert "FRIDAY_SELF_REPAIR_REVIEW_KEY" in only_control.missing()