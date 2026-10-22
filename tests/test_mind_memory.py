"""Tests for shared episodic recall and the per-agent minds.

Every test writes to `tmp_path`. Nothing here touches `data/` in the repository,
and nothing reaches the network: the Memora mirror is exercised through the
in-process contract harness.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from friday.cognition.memory_bridge import Episode, SharedMemory, mesh_mirror
from friday.cognition.mesh import ContractTransport, HarnessBehaviour, Mesh, build_contracts
from friday.cognition.mind import CapabilityLedger, Mind, MindRegistry


@pytest.fixture()
def memory(tmp_path: Path) -> SharedMemory:
    return SharedMemory(tmp_path / "episodes.jsonl")


@pytest.fixture()
def minds(tmp_path: Path, memory: SharedMemory) -> MindRegistry:
    registry = MindRegistry(memory=memory)
    registry.register(
        Mind(
            "friday",
            "local_os",
            purpose="run the desktop",
            tools=["run_tests", "write_code_file", "self_repair"],
            memory=memory,
            directory=tmp_path / "minds",
        )
    )
    registry.register(
        Mind(
            "forge",
            "software_engineering",
            purpose="write code",
            tools=["delegate"],
            memory=memory,
            directory=tmp_path / "minds",
        )
    )
    return registry


# ── shared memory ─────────────────────────────────────────────────────────


def test_an_episode_is_durable_across_process_lifetime(tmp_path: Path) -> None:
    path = tmp_path / "episodes.jsonl"
    first = SharedMemory(path)
    first.record("repaired the parser test", agent="friday", capability="source_repair", success=True)

    second = SharedMemory(path)

    assert len(second.all()) == 1
    assert second.all()[0].summary == "repaired the parser test"
    assert second.all()[0].success is True


def test_recall_matches_on_tokens_and_says_why(memory: SharedMemory) -> None:
    memory.record("repaired the failing parser test", agent="friday", capability="source_repair", success=True)
    memory.record("sent a briefing email", agent="friday", capability="email", success=True)

    hits = memory.recall("parser failing")

    assert hits, "a lexical match on 'parser'/'failing' must be found"
    assert hits[0].episode.capability == "source_repair"
    assert "matched" in hits[0].why
    assert hits[0].score > 0


def test_recall_returns_nothing_rather_than_a_bad_match(memory: SharedMemory) -> None:
    memory.record("repaired the parser test", agent="friday")

    assert memory.recall("quarterly tax return") == []
    assert memory.recall("") == []


def test_recall_prefers_the_more_recent_of_two_equal_matches(memory: SharedMemory) -> None:
    memory.record("restarted the widget service", agent="friday")
    memory.record("restarted the widget service again", agent="friday")

    hits = memory.recall("widget service")
    assert len(hits) == 2
    assert hits[0].episode.summary.endswith("again")


def test_a_corrupt_line_does_not_lose_the_rest_of_the_history(tmp_path: Path) -> None:
    path = tmp_path / "episodes.jsonl"
    memory = SharedMemory(path)
    memory.record("the first episode", agent="friday")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")
    memory.record("the third episode", agent="friday")

    reloaded = SharedMemory(path)

    summaries = [episode.summary for episode in reloaded.all()]
    assert summaries == ["the first episode", "the third episode"]


def test_success_rates_are_computed_from_records_not_assumed(memory: SharedMemory) -> None:
    for success in (True, True, False):
        memory.record("attempt", agent="friday", capability="source_repair", success=success)

    rate = memory.success_rate(capability="source_repair")

    assert rate == {"samples": 3, "successes": 2, "failures": 1, "rate": 0.667}
    assert memory.success_rate(capability="never_attempted")["rate"] is None


def test_lessons_need_a_minimum_number_of_samples(memory: SharedMemory) -> None:
    memory.record("one attempt", agent="friday", capability="lonely", success=True)
    assert memory.lessons(min_samples=2) == []

    memory.record("second attempt", agent="friday", capability="lonely", success=True)
    lessons = memory.lessons(min_samples=2)

    assert len(lessons) == 1
    assert lessons[0]["success_rate"] == 1.0
    assert lessons[0]["reading"] == "reliable so far"


def test_status_is_explicit_that_retrieval_is_lexical(memory: SharedMemory) -> None:
    status = memory.status()

    assert "lexical" in status["retrieval_mode"]
    assert "CONFIGURED-BUT-UNVERIFIED" in status["semantic_retrieval"]


def test_the_store_is_bounded(memory: SharedMemory) -> None:
    memory.limit = 5
    for index in range(12):
        memory.record(f"attempt {index}", agent="friday")

    assert len(memory.all()) == 5
    assert memory.all()[-1].summary == "attempt 11"


# ── the Memora mirror ─────────────────────────────────────────────────────


def test_episodes_mirror_to_the_harness_memora_peer(tmp_path: Path) -> None:
    contracts = build_contracts()
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    memory = SharedMemory(tmp_path / "episodes.jsonl", mirror=mesh_mirror(mesh))

    memory.record("a repair worth remembering", agent="friday", capability="source_repair", success=True)

    assert memory.status()["mirror_outcomes"]["COMPLETED"] == 1
    assert any(call.peer == "memora" for call in harness.calls)


def test_a_failed_mirror_does_not_lose_the_local_episode(tmp_path: Path) -> None:
    contracts = build_contracts()
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    harness.behave("memora", HarnessBehaviour(raise_transport_error=True))
    memory = SharedMemory(tmp_path / "episodes.jsonl", mirror=mesh_mirror(mesh))

    episode = memory.record("proof survives the outage", agent="friday")

    assert episode.episode_id
    assert [event.summary for event in memory.all()] == ["proof survives the outage"]
    assert memory.status()["mirror_outcomes"]["UNREACHABLE"] == 1


def test_a_mirror_that_returns_200_without_a_receipt_is_not_counted_as_stored(tmp_path: Path) -> None:
    contracts = build_contracts()
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    harness.behave("memora", HarnessBehaviour(receipt=False))
    memory = SharedMemory(tmp_path / "episodes.jsonl", mirror=mesh_mirror(mesh))

    memory.record("claimed but unproven", agent="friday")

    assert memory.status()["mirror_outcomes"]["UNVERIFIED"] == 1


# ── the ledger ────────────────────────────────────────────────────────────


def test_confidence_accounts_for_small_samples() -> None:
    ledger = CapabilityLedger()
    ledger.observe("do_a_thing", True)

    record = ledger.get("do_a_thing")
    assert record is not None
    assert record.confidence == pytest.approx(2 / 3)
    assert record.successes == 1
    assert record.attempts == 1


def test_consecutive_failures_are_tracked_and_reset() -> None:
    ledger = CapabilityLedger()
    ledger.observe("do_a_thing", False)
    ledger.observe("do_a_thing", False)
    assert ledger.get("do_a_thing").consecutive_failures == 2  # type: ignore[union-attr]

    ledger.observe("do_a_thing", True)
    assert ledger.get("do_a_thing").consecutive_failures == 0  # type: ignore[union-attr]


def test_best_and_weakest_are_evidence_based() -> None:
    ledger = CapabilityLedger()
    for _ in range(4):
        ledger.observe("solid", True)
    ledger.observe("shaky", True)
    ledger.observe("shaky", False)
    ledger.observe("shaky", False)

    assert ledger.best() == "solid"
    assert ledger.weakest()[0].name == "shaky"


# ── the mind ──────────────────────────────────────────────────────────────


def test_a_mind_with_no_history_says_so_instead_of_boasting(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None

    verdict = friday.can("source_repair")

    assert verdict["answer"] == "no_evidence"
    assert "unknown — not yes and not no" in verdict["why"]
    assert "no recorded attempts" in friday.reflect()


def test_the_ledger_learns_from_outcomes_and_reports_confidence(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None
    for _ in range(5):
        friday.observe("source_repair", True, detail="failing test went green")

    verdict = friday.can("source_repair")

    assert verdict["answer"] == "evidence_supports"
    assert verdict["samples"] == 5
    assert verdict["confidence"] == 0.857
    assert "5/5 recorded attempts succeeded" in verdict["why"]


def test_repeated_recent_failures_override_an_old_good_record(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None
    for _ in range(6):
        friday.observe("source_repair", True)
    for _ in range(3):
        friday.observe("source_repair", False, detail="the patch regressed")

    verdict = friday.can("source_repair")

    assert verdict["answer"] == "evidence_against"
    assert "recent evidence is poor" in verdict["why"]


def test_an_agent_that_only_ever_failed_is_reported_as_such(minds: MindRegistry) -> None:
    forge = minds.for_agent("forge")
    assert forge is not None
    forge.observe("delegate", False, detail="peer unreachable")
    forge.observe("delegate", False)

    verdict = forge.can("delegate")

    assert verdict["answer"] == "evidence_against"
    assert "none successful" in verdict["why"]


def test_an_outcome_becomes_a_shared_episode_readable_by_another_agent(
    minds: MindRegistry, memory: SharedMemory
) -> None:
    friday = minds.for_agent("friday")
    forge = minds.for_agent("forge")
    assert friday is not None and forge is not None

    friday.observe("source_repair", True, detail="fixed the failing import test")

    # The other agent sees it, even though it did not do the work.
    other_agent_view = forge.recall("failing import test")
    assert other_agent_view, "an agent must be able to recall another agent's work"
    assert other_agent_view[0].episode.agent == "friday"
    assert memory.agents() == ["friday"]


def test_the_self_model_separates_reliable_from_untested(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None
    for _ in range(3):
        friday.observe("run_tests", True)

    model = friday.self_model()

    assert "run_tests" in model.reliable
    assert "write_code_file" in model.untested
    assert model.samples == 3
    assert set(model.tools) >= {"run_tests", "write_code_file", "self_repair"}
    assert model.as_dict()["agent_id"] == "friday"


def test_the_ledger_survives_a_restart(tmp_path: Path, memory: SharedMemory) -> None:
    directory = tmp_path / "minds"
    first = Mind("friday", "local_os", memory=memory, directory=directory)
    first.observe("source_repair", True)
    first.observe("source_repair", False)
    first.save()

    reloaded = Mind("friday", "local_os", memory=memory, directory=directory)
    record = reloaded.ledger.get("source_repair")

    assert record is not None
    assert record.attempts == 2
    assert record.successes == 1


def test_a_corrupt_mind_file_starts_fresh_and_says_so(tmp_path: Path, memory: SharedMemory) -> None:
    directory = tmp_path / "minds"
    directory.mkdir(parents=True)
    (directory / "friday.json").write_text("{ broken", encoding="utf-8")

    mind = Mind("friday", "local_os", memory=memory, directory=directory)

    assert mind.ledger.known() == []


def test_finish_records_a_whole_task(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None

    record = friday.finish("fix the failing parser test", success=True, output="1 passed")

    assert record.attempts == 1
    assert friday.can("local_os.task")["answer"] == "evidence_supports"
    assert "completed" in friday.memory.recent(1)[0].summary


def test_finish_names_the_tool_it_used(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None

    friday.finish("run the suite", success=True, tool_calls=["run_tests"])

    assert friday.ledger.get("run_tests") is not None


# ── the registry, and agents finding each other ───────────────────────────


def test_the_registry_chooses_the_agent_with_evidence(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    forge = minds.for_agent("forge")
    assert friday is not None and forge is not None
    for _ in range(4):
        forge.observe("write_code", True)
    friday.observe("write_code", False)

    choice = minds.consult("write_code")

    assert choice["chosen"] == "forge"
    assert "4/4" in choice["why"]


def test_a_capability_nobody_has_done_is_not_awarded_to_anyone(minds: MindRegistry) -> None:
    choice = minds.consult("teleport")

    assert choice["chosen"] is None
    assert "no agent on this host" in choice["why"]


def test_a_capability_only_ever_failed_is_not_awarded_either(minds: MindRegistry) -> None:
    forge = minds.for_agent("forge")
    assert forge is not None
    forge.observe("delegate", False)
    forge.observe("delegate", False)

    choice = minds.consult("delegate")

    assert choice["chosen"] is None
    assert "evidence against" in choice["why"]
    assert choice["candidates"], "the failing candidates must still be visible"


def test_who_can_lists_only_agents_with_a_record(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None
    friday.observe("source_repair", True)

    ranked = minds.who_can("source_repair")

    assert [item["agent_id"] for item in ranked] == ["friday"]
    assert minds.who_can("nothing_at_all") == []


def test_attaching_an_agent_gives_it_a_mind_and_registers_it(minds: MindRegistry) -> None:
    class FakeAgent:
        agent_id = "sentinel"
        role = "security"
        instructions = "watch for threats"
        allowed_tools = ["run_tests"]
        tool_registry = None

    agent = FakeAgent()
    mind = minds.attach(agent)

    assert mind.agent_id == "sentinel"
    assert minds.for_agent("sentinel") is mind
    assert agent.mind is mind


def test_attaching_is_idempotent(minds: MindRegistry) -> None:
    class FakeAgent:
        agent_id = "cortex"
        role = "web"
        instructions = "scrape"
        allowed_tools: list[str] = []
        tool_registry = None

    first = minds.attach(FakeAgent())
    second = minds.attach(FakeAgent())
    third = minds.attach(FakeAgent())

    assert first is second is third, "two handles on one agent must share one ledger"


def test_fleet_status_reports_every_mind_and_the_shared_memory(minds: MindRegistry) -> None:
    friday = minds.for_agent("friday")
    assert friday is not None
    friday.observe("run_tests", True)
    friday.observe("run_tests", True)

    status = minds.fleet_status()

    assert status["agents"] == 2
    assert {mind["agent_id"] for mind in status["minds"]} == {"friday", "forge"}
    assert status["memory"]["episodes"] == 2
    assert any(lesson["capability"] == "run_tests" for lesson in status["lessons"])


def test_status_is_json_serialisable(minds: MindRegistry) -> None:
    status = minds.for_agent("friday").status()  # type: ignore[union-attr]
    json.dumps(status, default=str)  # raises if something exotic leaked in
    assert status["mind_file"]


# ── the episode type ──────────────────────────────────────────────────────


def test_an_unknown_episode_kind_falls_back_rather_than_being_stored_as_unknown() -> None:
    episode = Episode(summary="x", kind="not_a_kind")
    assert episode.kind == "observation"


def test_an_episode_round_trips_through_json() -> None:
    episode = Episode(summary="s", agent="a", tags=("t1",), evidence={"k": 1}, success=True)
    restored = Episode.from_dict(json.loads(json.dumps(episode.as_dict(), default=str)))

    assert restored.summary == episode.summary
    assert restored.tags == ("t1",)
    assert restored.success is True
    assert restored.one_line() == "[a/task/ok] s"


def test_an_episode_with_no_known_outcome_is_labelled_unknown() -> None:
    assert "unknown" in Episode(summary="just an observation").one_line()


def test_minds_and_memory_share_one_store_without_network(
    tmp_path: Path, memory: SharedMemory
) -> None:
    """A last end-to-end check: three agents, one memory, no egress."""
    registry = MindRegistry(memory=memory)
    for name in ("friday", "forge", "sentinel"):
        registry.register(Mind(name, "specialist", memory=memory, directory=tmp_path / "minds"))

    registry.for_agent("forge").observe("write_code", True, detail="built the module")  # type: ignore[union-attr]
    registry.for_agent("sentinel").observe("audit", True, detail="found the open port")  # type: ignore[union-attr]

    friday = registry.for_agent("friday")
    assert friday is not None
    assert len(friday.recall("open port")) == 1
    assert len(friday.recall("built the module")) == 1
    assert memory.agents() == ["forge", "sentinel"]
    assert asyncio.run(_noop()) is None


async def _noop() -> None:
    return None
