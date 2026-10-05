"""Extreme-pressure tests: the parts a green unit suite never touches.

Everything here is deliberately hostile, and every test was written to be able to
*find* something rather than to confirm what was already believed. Doing this
found three real defects, all of them on paths a polite test would have missed:

* a hung transport hung the mesh forever - no transport had a bound the mesh
  itself enforced, so a peer that accepted a connection and never answered was
  indistinguishable from a frozen process. Now every request is bounded by
  `Mesh.request_timeout`, whatever transport is in use;
* the circuit breaker counted each unreachable attempt twice, and a locally
  blocked call reset it - so a breaker that read correctly never tripped at the
  threshold, and could be cleared by the very outage it existed to survive;
* an autonomous repair commit ran `git add -A` and swept the owner's work in
  progress and the agent's own runtime state into the repair (fixed and covered
  in tests/test_repair_commit_scope.py).

The rest of these tests are the pressure that keeps those three honest: hundreds
of concurrent dispatches, megabytes of junk from a peer, thousands of episodes,
dozens of agents writing from threads, many faults at once, and an incident whose
file changed underneath it before the repair could land.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from friday.cognition.memory_bridge import SharedMemory
from friday.cognition.mesh import (
    CircuitBreaker,
    ContractTransport,
    HarnessBehaviour,
    Mesh,
    OutcomeState,
    PeerRequest,
    PeerResponse,
    TransportError,
    build_contracts,
)
from friday.cognition.mind import Mind, MindRegistry
from friday.core.task_envelope import ActionReceipt, TaskEnvelope, TaskResult

# ── a transport that misbehaves on purpose ────────────────────────────────


class HostileTransport:
    """A transport that behaves like a badly broken network."""

    def __init__(self, script: dict[str, str]) -> None:
        self.script = script
        self.calls = 0

    async def send(self, request: PeerRequest) -> PeerResponse:
        self.calls += 1
        behaviour = self.script.get(request.peer, "healthy")
        if behaviour == "hang":
            await asyncio.sleep(300)
            raise AssertionError("unreachable")
        if behaviour == "garbage":
            return PeerResponse(status_code=200, body=None, text="<html>not json at all</html>")
        if behaviour == "huge":
            blob = "x" * (10 * 1024 * 1024)
            return PeerResponse(status_code=200, body={"data": blob}, text=blob)
        if behaviour == "wrong_receipt":
            return PeerResponse(
                status_code=200,
                body={
                    "task_id": "t",
                    "status": "success",
                    "receipt": {
                        "requested_action": "a_completely_different_action",
                        "target": request.peer,
                        "authorization_decision": "AUTHORIZED",
                        "verification_evidence": {"checked": True},
                    },
                },
            )
        if behaviour == "explode":
            raise RuntimeError("the transport itself is broken")
        return PeerResponse(status_code=200, body={"status": "ok", "response": "fine"})


@pytest.fixture()
def contracts() -> dict[str, Any]:
    built = build_contracts()
    for contract in built.values():
        contract.api_key = contract.api_key or "pressure-key"
    return built


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    ).stdout.strip()


# ── the mesh under load ───────────────────────────────────────────────────


def test_two_hundred_concurrent_dispatches_all_come_back(contracts: dict[str, Any]) -> None:
    """Every task gets exactly one typed outcome, with no exception escaping."""
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    peers = sorted(contracts)
    behaviours = [
        HarnessBehaviour(),  # healthy
        HarnessBehaviour(raise_transport_error=True),  # unreachable
        HarnessBehaviour(status_code=503),  # degraded
        HarnessBehaviour(status_code=403),  # refused
        HarnessBehaviour(status_code=202),  # pending
        HarnessBehaviour(receipt=False),  # unverified
        HarnessBehaviour(body={"status": "ok", "response": "legacy"}),  # no receipt
        HarnessBehaviour(status_code=500),  # degraded again
    ]
    for peer, behaviour in zip(peers, behaviours, strict=True):
        harness.behave(peer, behaviour)

    async def storm() -> list[Any]:
        tasks = [
            mesh.dispatch(peer, f"action_{index}", attempts=1)
            for index in range(200)
            for peer in [peers[index % len(peers)]]
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    outcomes = run(storm())

    assert len(outcomes) == 200
    assert not [item for item in outcomes if isinstance(item, BaseException)]
    assert len(mesh.history) == 200
    states = {outcome.state for outcome in outcomes}
    assert states <= set(OutcomeState)
    # A peer that never answered must never be reported as degraded.
    unreachable = [o for o in outcomes if o.peer == peers[1]]
    assert unreachable and all(o.state is OutcomeState.UNREACHABLE for o in unreachable)


def test_the_breaker_counts_every_attempt_once(contracts: dict[str, Any]) -> None:
    """Double counting is invisible until the breaker is asked to be exact."""
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    mesh.breaker = CircuitBreaker(threshold=100, cooldown_seconds=300)
    harness.behave("forge", HarnessBehaviour(raise_transport_error=True))

    run(mesh.dispatch("forge", "a", attempts=3))
    run(mesh.dispatch("forge", "b", attempts=2))

    # Five real attempts must mean five recorded failures. This assertion is the
    # point of the test: `_attempt` reported every unreachable attempt, and
    # `dispatch` then reported the final one again, so the count was 51 for 25
    # attempts - a breaker that never tripped where it should have.
    assert mesh.breaker._failures["forge"] == 5, (
        f"each attempt is one measurement; recorded {mesh.breaker._failures['forge']} for 5"
    )


def test_a_locally_blocked_call_does_not_forgive_a_dead_peer(contracts: dict[str, Any]) -> None:
    """The circuit must not be cleared by the block it produced."""
    mesh, harness = Mesh.in_process(contracts, backoff_seconds=0.0)
    mesh.breaker = CircuitBreaker(threshold=2, cooldown_seconds=300)
    harness.behave("cortex", HarnessBehaviour(raise_transport_error=True))

    run(mesh.dispatch("cortex", "a", attempts=1))
    run(mesh.dispatch("cortex", "b", attempts=1))
    assert mesh.breaker.is_open("cortex") is True

    blocked = run(mesh.dispatch("cortex", "c", attempts=1))

    assert blocked.state is OutcomeState.BLOCKED
    assert mesh.breaker.is_open("cortex") is True, "a local block proves nothing about the peer"


def test_a_peer_that_never_answers_is_bounded_by_the_request_timeout(
    contracts: dict[str, Any],
) -> None:
    """A transport that sleeps forever must not become a mesh that never returns."""
    transport = HostileTransport({"forge": "hang"})
    mesh = Mesh(contracts=contracts, transport=transport, attempts=1, request_timeout=0.05)

    started = time.monotonic()
    outcome = run(mesh.dispatch("forge", "build"))
    elapsed = time.monotonic() - started

    assert outcome.state is OutcomeState.UNREACHABLE
    assert "within 0.1s" in outcome.detail or "within" in outcome.detail
    assert elapsed < 3.0, f"a hung peer held the mesh for {elapsed:.1f}s"
    assert not outcome.verified


def test_ten_megabytes_of_junk_from_a_peer_is_classified_not_absorbed(
    contracts: dict[str, Any],
) -> None:
    mesh = Mesh(contracts=contracts, transport=HostileTransport({"forge": "huge"}), attempts=1)

    outcome = run(mesh.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.UNVERIFIED
    assert "no receipt" in outcome.detail.lower() or "receipt" in outcome.detail.lower()


def test_html_instead_of_json_is_unverified_with_the_reason(contracts: dict[str, Any]) -> None:
    mesh = Mesh(contracts=contracts, transport=HostileTransport({"forge": "garbage"}), attempts=1)

    outcome = run(mesh.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.UNVERIFIED
    assert "non-JSON" in outcome.detail or "no receipt" in outcome.detail


def test_a_receipt_naming_another_action_never_completes(contracts: dict[str, Any]) -> None:
    mesh = Mesh(contracts=contracts, transport=HostileTransport({"forge": "wrong_receipt"}), attempts=1)

    outcome = run(mesh.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.UNVERIFIED
    assert not outcome.verified


def test_a_transport_that_explodes_is_unreachable_not_an_exception(
    contracts: dict[str, Any],
) -> None:
    mesh = Mesh(contracts=contracts, transport=HostileTransport({"forge": "explode"}), attempts=2)

    outcome = run(mesh.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.UNREACHABLE
    assert outcome.attempts == 2


def test_the_mesh_survives_a_transport_that_raises_inside_the_breaker(
    contracts: dict[str, Any],
) -> None:
    """A listener that throws must not take the dispatch down with it."""
    problems: list[str] = []

    def bad_listener(_outcome: Any) -> None:
        problems.append("called")
        raise RuntimeError("the listener is broken")

    mesh = Mesh(
        contracts=contracts,
        transport=ContractTransport(contracts),
        on_outcome=bad_listener,
        attempts=1,
        backoff_seconds=0.0,
    )

    outcome = run(mesh.dispatch("forge", "build"))

    assert outcome.state is OutcomeState.COMPLETED
    assert problems, "the listener was never exercised"


# ── memory under load ─────────────────────────────────────────────────────


def test_five_thousand_episodes_with_corruption_still_recall(tmp_path: Path) -> None:
    path = tmp_path / "episodes.jsonl"
    memory = SharedMemory(path, limit=6000)
    for index in range(5000):
        memory.record(
            f"routine observation {index}",
            agent=f"agent_{index % 9}",
            capability="observe",
            success=True,
        )
    with path.open("a", encoding="utf-8") as handle:
        for index in range(50):
            handle.write("{ truncated json\n")
    memory.record("the parser import test failed and I repaired it", agent="friday", success=True)

    started = time.monotonic()
    hits = memory.recall("parser import test failed")
    elapsed = time.monotonic() - started

    assert hits and "parser" in hits[0].why
    assert elapsed < 5.0, f"recall over 5000 episodes took {elapsed:.2f}s"
    assert len(memory.all()) <= 6001
    assert len(memory.agents()) == 10


def test_the_store_stays_bounded_under_a_flood(tmp_path: Path) -> None:
    memory = SharedMemory(tmp_path / "episodes.jsonl", limit=50)
    for index in range(500):
        memory.record(f"flood {index}", agent="friday")

    assert len(memory.all()) == 50
    # The file itself must not grow without bound either.
    lines = (tmp_path / "episodes.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) <= 50


# ── agents under load ─────────────────────────────────────────────────────


def test_sixty_agents_writing_from_threads_lose_no_write(tmp_path: Path) -> None:
    memory = SharedMemory(tmp_path / "episodes.jsonl", limit=10000)
    registry = MindRegistry(memory=memory)
    for index in range(60):
        registry.register(
            Mind(f"agent_{index}", "specialist", memory=memory, directory=tmp_path / "minds")
        )

    errors: list[BaseException] = []

    def work(agent_index: int) -> None:
        mind = registry.for_agent(f"agent_{agent_index}")
        assert mind is not None
        try:
            for _ in range(5):
                mind.observe("run_tests", True, remember=False)
        except BaseException as exc:  # pragma: no cover - reported through `errors`
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(60)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"concurrent ledger writes raised: {errors[:3]}"
    total = sum(
        record.attempts
        for mind in registry.all()
        for record in mind.ledger.records.values()
    )
    assert total == 60 * 5, f"lost writes: {total} recorded of 300"


def test_concurrent_observations_of_the_same_capability_keep_the_arithmetic(
    tmp_path: Path,
) -> None:
    memory = SharedMemory(tmp_path / "episodes.jsonl", limit=10000)
    mind = Mind("friday", "local_os", memory=memory, directory=tmp_path / "minds")

    def work(success: bool) -> None:
        for _ in range(25):
            mind.observe("source_repair", success, remember=False)

    threads = [threading.Thread(target=work, args=(True,)), threading.Thread(target=work, args=(False,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    record = mind.ledger.get("source_repair")
    assert record is not None
    assert record.attempts == 50
    assert record.successes + record.failures == 50


# ── the reflex under many faults ──────────────────────────────────────────


@pytest.fixture()
def many_faults_repo(tmp_path: Path) -> Path:
    """Eight independent faults in one real repository."""
    repo = tmp_path / "at_scale"
    (repo / "src" / "friday").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "conftest.py").write_text(
        "import pathlib, sys\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'src'))\n",
        encoding="utf-8",
    )
    (repo / "src" / "friday" / "__init__.py").write_text("", encoding="utf-8")
    for index in range(8):
        (repo / "src" / "friday" / f"mod_{index}.py").write_text(
            f"def value_{index}():\n    return totl_{index}\n", encoding="utf-8"
        )
        (repo / "tests" / f"test_mod_{index}.py").write_text(
            f"from friday.mod_{index} import value_{index}\n\n"
            f"def test_value_{index}():\n    assert value_{index}() == {index}\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "o@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Owner"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "eight faults"], cwd=repo, check=True)
    return repo


def test_the_detector_finds_every_fault_at_once(many_faults_repo: Path) -> None:
    from friday.cognition.reflex import IncidentDetector, IncidentKind

    detector = IncidentDetector(many_faults_repo)
    incidents = detector.scan_tests()

    assert len(incidents) == 8, f"found {len(incidents)} of 8 faults"
    assert {incident.kind for incident in incidents} == {IncidentKind.TEST_FAILURE}
    assert all(incident.evidence.get("exception_type") == "NameError" for incident in incidents)
    assert all(incident.evidence.get("source_file") for incident in incidents)


def test_many_faults_are_acted_on_without_touching_the_tree_and_without_lying(
    many_faults_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No mandate: every fault may be diagnosed, and none may be repaired."""
    from friday.cognition.reflex import IncidentKind, ReflexBrain

    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(tmp_path / "mandates.json"))
    monkeypatch.delenv("FRIDAY_AUTONOMY_KEY", raising=False)
    brain = ReflexBrain(repo_root=many_faults_repo)
    head_before = _git(many_faults_repo, "rev-parse", "HEAD")

    result = run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

    assert result["status"] == "COMPLETED"
    assert result["incidents"] == 8
    outcomes = result["outcomes"]
    assert len(outcomes) == 8
    # Every outcome is an honest terminal state, and none of them claims a repair.
    assert {outcome["status"] for outcome in outcomes} <= {
        "AWAITING_MANDATE",
        "UNPROVEN",
        "NO_FIX_KNOWN",
        "REFUSED",
        "ESCALATED",
        "OBSERVED",
        "ROLLED_BACK",
    }
    assert _git(many_faults_repo, "rev-parse", "HEAD") == head_before
    # Nothing the brain did may change a tracked file. (Bytecode caches are not
    # a change to the repository; they are what running Python looks like.)
    dirty = [
        line
        for line in _git(many_faults_repo, "status", "--porcelain").splitlines()
        if "__pycache__" not in line and not line.strip().endswith(".pyc")
    ]
    assert dirty == [], f"the brain modified the tree while holding no mandate: {dirty}"


def test_one_sleeping_test_is_bounded_by_the_runner_timeout(tmp_path: Path) -> None:
    """A test suite that hangs must not hang the brain that is diagnosing it."""
    from friday.cognition.reflex import IncidentDetector, RepairRunner
    from friday.cognition.patcher import CompositePatcher

    repo = tmp_path / "sleepy"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_slow.py").write_text(
        "import time\n\n\ndef test_that_never_finishes():\n    time.sleep(120)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)

    # The detector's budget for the whole suite is `test_timeout`; the runner's
    # budget for one test must be shorter or a stuck test is waited on past the
    # point where the report still means anything. The production defaults are a
    # 900s suite budget against a 600s single-test budget.
    detector = IncidentDetector(repo, test_timeout=3)
    runner = RepairRunner(repo, CompositePatcher(), timeout=2)
    assert runner.timeout < detector.test_timeout, (
        "a single test may not be allowed to outlive the run that measured it"
    )

    started = time.monotonic()
    incidents = detector.scan_tests()
    elapsed_scan = time.monotonic() - started

    # The detector must have given up long before the test it was measuring would
    # have finished, and it must say so.
    assert elapsed_scan < 30, f"the detector waited {elapsed_scan:.0f}s on a 3s budget"
    assert incidents, "a suite that times out is an incident, not silence"
    assert "did not finish" in incidents[0].summary
    if incidents:
        code, output = runner._run_test("tests/test_slow.py", repo)
        assert code == 124
        assert "timed out" in output


# ── the file changes underneath the repair ────────────────────────────────


def test_a_repair_is_refused_when_the_file_drifted_after_review(tmp_path: Path) -> None:
    """Somebody else editing the file is the ordinary case, not the exotic one."""
    from friday.autonomous.self_repair import GitRepairApplier, RepairProposal, SelfRepairGate

    repo = tmp_path / "drifted"
    (repo / "src" / "friday").mkdir(parents=True)
    target = repo / "src" / "friday" / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "o@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Owner"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "broken"], cwd=repo, check=True)
    applier = GitRepairApplier(str(repo))
    gate = SelfRepairGate(applier, review_verification_key=b"pressure-key")

    record, receipt = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="reflex/drifted",
            base_commit=applier.current_commit() or "HEAD",
            target_file="src/friday/calc.py",
            original_snippet="    return a - b\n",
            replacement_snippet="    return a + b\n",
            rationale="add() subtracts",
            proposed_by="friday",
            test_evidence={"command": "pytest -q", "passed": True, "summary": "1 passed"},
        )
    )
    assert receipt.outcome == "ACCEPTED"

    # The owner edits the same function between the proposal and the apply.
    target.write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")

    # A clear review and the owner's decision, through the real gate, so the
    # apply step is reached legitimately and the refusal below is about drift.
    _file_a_clearing_review(gate, record.patch_id)
    approval_receipt = gate.record_owner_decision(
        record.patch_id, approver="surendra", approve=True
    )
    assert approval_receipt.outcome == "ACCEPTED", approval_receipt.detail

    applied = gate.apply(record.patch_id)

    assert applied.outcome == "REFUSED"
    assert "GIT_FAILED" in applied.detail
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a * b\n"
    assert _git(repo, "log", "--oneline").count("\n") + 1 == 1, "no repair commit was created"


def _file_a_clearing_review(gate: Any, patch_id: str) -> None:
    """Sign a real review for this patch and file it through the gate."""
    from friday.cognition.reviewer import LocalReviewer

    record = gate.get(patch_id)
    reviewer = LocalReviewer(b"pressure-key", reviewer_id="sentinel")
    outcome = reviewer.review(
        patch_fingerprint=record.proposal.fingerprint(),
        target_file=record.proposal.target_file,
        replacement_snippet=record.proposal.replacement_snippet,
        original_snippet=record.proposal.original_snippet,
        current_source="def add(a, b):\n    return a - b\n",
        test_evidence={"command": "pytest -q", "passed": True, "summary": "1 passed"},
        approval_id="pressure-approval",
    )
    assert outcome.cleared is True, outcome.reasons
    receipt = gate.record_review(patch_id, outcome.document)
    assert receipt.outcome == "ACCEPTED", receipt.detail


# ── concurrency in capability synthesis ───────────────────────────────────


def test_concurrent_synthesis_never_leaves_a_partial_tool(tmp_path: Path) -> None:
    """Ten threads synthesising at once: every file on disk must be complete."""
    from friday.cognition.capability import CapabilityGap, ToolSynthesiser

    class NoModel:
        def generate(self, messages: Any, **_: Any) -> Any:
            raise RuntimeError("no model under pressure")

    (tmp_path / "src" / "friday" / "tools" / "builtin").mkdir(parents=True)
    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def work(index: int) -> None:
        synthesiser = ToolSynthesiser(tmp_path, llm=NoModel())
        try:
            results.append(
                synthesiser.synthesise(
                    CapabilityGap(capability=f"pressure capability {index}", rationale="stress")
                )
            )
        except BaseException as exc:  # pragma: no cover - reported through `errors`
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"synthesis raised under concurrency: {errors[:3]}"
    written = sorted((tmp_path / "src" / "friday" / "tools" / "builtin").glob("*.py"))
    assert written, "nothing was written at all"
    for path in written:
        source = path.read_text(encoding="utf-8")
        assert source.endswith("\n"), f"{path.name} was written mid-flight"
        compile(source, str(path), "exec")  # every file on disk must be valid Python
    assert all(result["verified"] for result in results)
    assert not list((tmp_path / "src" / "friday" / "tools" / "builtin").glob("*.tmp"))


# ── a mandate that is present but wrong ───────────────────────────────────


def test_an_expired_mandate_is_refused_by_name(tmp_path: Path) -> None:
    from friday.cognition.mandate import AutonomyMandate, MandateAuthority, MandateLedger

    authority = MandateAuthority(key=b"pressure-key", ledger=MandateLedger(str(tmp_path / "m.json")))
    document = authority.issue("surendra", scopes=("source_repair",), ttl_seconds=60)
    # Rewrite the expiry to the past and re-sign it with the owner's key. A clock
    # moving is not an attack; it must still be refused.
    mandate = AutonomyMandate.from_document(document)
    mandate.expires_at = mandate.issued_at - 1
    expired = mandate.sign(b"pressure-key")
    authority._ledger.record_grant(expired)

    verdict = authority.evaluate("source_repair", paths=("src/friday/calc.py",))

    assert verdict.allowed is False
    assert verdict.refusal in {"EXPIRED", "NO_MANDATE"}
    authority._ledger.record_revocation(mandate.mandate_id)
    after_revocation = authority.evaluate("source_repair", paths=("src/friday/calc.py",))
    assert after_revocation.allowed is False


def test_a_mandate_for_one_scope_does_not_authorise_another(tmp_path: Path) -> None:
    from friday.cognition.mandate import MandateAuthority, MandateLedger

    authority = MandateAuthority(key=b"pressure-key", ledger=MandateLedger(str(tmp_path / "m.json")))
    authority.issue("surendra", scopes=("source_repair",), ttl_seconds=600)

    allowed = authority.evaluate("source_repair", paths=("src/friday/calc.py",))
    other = authority.evaluate("dependency_install")

    assert allowed.allowed is True
    assert other.allowed is False
    assert other.refusal == "SCOPE_NOT_GRANTED"


def test_a_mandate_does_not_cover_a_file_outside_its_paths(tmp_path: Path) -> None:
    from friday.cognition.mandate import MandateAuthority, MandateLedger

    authority = MandateAuthority(key=b"pressure-key", ledger=MandateLedger(str(tmp_path / "m.json")))
    authority.issue("surendra", scopes=("source_repair",), ttl_seconds=600)

    inside = authority.evaluate("source_repair", paths=("src/friday/calc.py",))
    outside = authority.evaluate("source_repair", paths=("../../etc/passwd",))
    home = authority.evaluate("source_repair", paths=("/home/owner/.ssh/id_rsa",))

    assert inside.allowed is True
    assert outside.allowed is False
    assert outside.refusal == "FILE_NOT_PERMITTED"
    assert home.allowed is False
    assert home.refusal == "FILE_NOT_PERMITTED"


def test_a_tampered_mandate_is_not_a_mandate(tmp_path: Path) -> None:
    from friday.cognition.mandate import MandateAuthority, MandateLedger, verify_mandate

    authority = MandateAuthority(key=b"pressure-key", ledger=MandateLedger(str(tmp_path / "m.json")))
    document = authority.issue("surendra", scopes=("source_repair",), ttl_seconds=600)

    for field, value in (
        ("allowed_paths", ["**"]),
        ("scopes", ["source_repair", "dependency_install", "runtime_cleanup"]),
        ("expires_at", 99_999_999_999.0),
        ("issued_by", "friday"),
    ):
        forged = dict(document)
        forged[field] = value
        assert verify_mandate(forged, b"pressure-key") is False, f"{field} could be changed"


def test_an_unproven_patch_cannot_be_approved(tmp_path: Path) -> None:
    """The last line of defence: no test evidence, no approval, no apply."""
    from friday.autonomous.self_repair import GitRepairApplier, RepairProposal, SelfRepairGate

    repo = tmp_path / "gate"
    (repo / "src" / "friday").mkdir(parents=True)
    (repo / "src" / "friday" / "calc.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    applier = GitRepairApplier(str(repo))
    gate = SelfRepairGate(applier, review_verification_key=b"pressure-key")

    record, receipt = gate.propose(
        RepairProposal(
            repo_path=str(repo),
            branch="reflex/unproven",
            base_commit=applier.current_commit() or "HEAD",
            target_file="src/friday/calc.py",
            original_snippet="value = 1\n",
            replacement_snippet="value = 2\n",
            rationale="no test evidence at all",
            proposed_by="friday",
        )
    )

    assert receipt.outcome == "REFUSED"
    assert "NO_TEST_EVIDENCE" in receipt.detail
    assert gate.apply(record.patch_id).outcome == "REFUSED"
    assert (repo / "src" / "friday" / "calc.py").read_text(encoding="utf-8") == "value = 1\n"
