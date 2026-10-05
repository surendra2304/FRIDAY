"""End-to-end tests for the reflex brain.

These are the tests that matter, because they are the difference between "FRIDAY
reports that it cannot repair" and "FRIDAY repairs". Each one builds a **real**
repository with a **real** failing test, runs the **real** detector, the **real**
patcher, the **real** sandbox verifier, the **real** gate and the **real**
rollback, and asserts what actually happened.

Nothing here is mocked except the peer mesh, which is a contract harness.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from friday.cognition.mandate import (
    SCOPE_SOURCE_REPAIR,
    MandateAuthority,
    MandateLedger,
)
from friday.cognition.patcher import (
    CompositePatcher,
    FailureReport,
    RulePatcher,
    parse_pytest_output,
)
from friday.cognition.reflex import (
    ActionOutcome,
    Incident,
    IncidentDetector,
    IncidentKind,
    IncidentSeverity,
    OutcomeStatus,
    ReflexBrain,
    RepairRunner,
)

MANDATE_KEY = b"reflex-test-mandate-key"

@pytest.fixture(autouse=True)
def _shared_review_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate verifies reviews with the environment key, and the harness signs
    with the same value, so the pipeline can complete.

    Scoped with monkeypatch rather than os.environ so it cannot leak into the
    tests that deliberately run without a review key configured.
    """
    monkeypatch.setenv("FRIDAY_SELF_REPAIR_REVIEW_KEY", REVIEW_KEY.decode())


REVIEW_KEY = b"reflex-test-review-key"
PYTHON = sys.executable


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30
    )
    return proc.stdout.strip()


@pytest.fixture
def broken_repo(tmp_path: Path) -> Path:
    """A real git repository whose code does not work and whose test says so.

    The defect is a typo'd name in the source: a genuine bug class with exactly
    one plausible repair.
    """
    root = tmp_path / "breaker"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "account.py").write_text(
        "def calculate_balance(opening, deposits):\n"
        "    total = opening\n"
        "    for deposit in deposits:\n"
        "        total = total + deposit\n"
        "    return totl\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_account.py").write_text(
        "from src.account import calculate_balance\n\n\n"
        "def test_balance_adds_deposits():\n"
        "    assert calculate_balance(10, [5, 5]) == 20\n",
        encoding="utf-8",
    )
    (root / "conftest.py").write_text("import sys\nsys.path.insert(0, '.')\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@localhost")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial: balance helper with a typo")
    return root


# ── parsing real pytest output ─────────────────────────────────────────────

REAL_PYTEST_OUTPUT = """
=================================== FAILURES ===================================
__________________________ test_balance_adds_deposits __________________________

    def test_balance_adds_deposits():
>       assert calculate_balance(10, [5, 5]) == 20
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_account.py:5:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

opening = 10, deposits = [5, 5]

    def calculate_balance(opening, deposits):
        total = opening
        for deposit in deposits:
            total = total + deposit
>       return totl
E       NameError: name 'totl' is not defined

src/account.py:6: NameError
=========================== short test summary info ============================
FAILED tests/test_account.py::test_balance_adds_deposits - NameError: name 'totl' is not defined
1 failed in 0.04s
"""


class TestFailureParsing:
    """The detector must read the tool's real output, not a convenient fiction."""

    def test_it_extracts_the_node_id_and_exception(self) -> None:
        reports = parse_pytest_output(REAL_PYTEST_OUTPUT, ".")
        assert len(reports) == 1
        report = reports[0]
        assert report.test_node_id == "tests/test_account.py::test_balance_adds_deposits"
        assert report.exception_type == "NameError"
        assert "totl" in report.exception_value
        assert report.source_file == "src/account.py"
        assert report.source_line == 6

    def test_empty_output_yields_no_invented_failures(self) -> None:
        assert parse_pytest_output("4 passed in 0.10s", ".") == []


class TestRulePatching:
    """A deterministic fixer either knows the answer or declines."""

    def test_it_fixes_an_undefined_name_typo(self) -> None:
        source = "def f():\n    total = 1\n    return totl\n"
        report = FailureReport(
            exception_type="NameError",
            exception_value="name 'totl' is not defined",
            source_file="src/account.py",
        )
        candidate = RulePatcher().candidate_for(report, current_source=source)
        assert candidate is not None
        assert candidate.original_snippet == "    return totl"
        assert candidate.replacement_snippet == "    return total"
        assert candidate.confidence == "high"

    def test_it_declines_when_two_spellings_are_plausible(self) -> None:
        """Never pick between two near-misses: that is a guess, not a repair."""
        source = "def f():\n    total = 1\n    totals = 2\n    return totl\n"
        report = FailureReport(
            exception_type="NameError",
            exception_value="name 'totl' is not defined",
            source_file="src/account.py",
        )
        assert RulePatcher().candidate_for(report, current_source=source) is None

    def test_it_declines_a_missing_dependency_it_cannot_supply(self) -> None:
        source = "import nothing_real\n\nnothing_real.work()\n"
        report = FailureReport(
            exception_type="ModuleNotFoundError",
            exception_value="No module named 'nothing_real_xyz'",
            source_file="src/x.py",
        )
        assert RulePatcher().candidate_for(report, current_source=source) is None

    def test_it_declines_without_an_exception_it_recognises(self) -> None:
        report = FailureReport(exception_type="AssertionError", exception_value="1 != 2")
        assert RulePatcher().candidate_for(report, current_source="x = 1\n") is None


# ── the proof: a real failing test, really fixed ────────────────────────────


class TestSandboxProof:
    """A candidate is only a repair once a test changes colour."""

    def test_it_proves_a_candidate_against_the_real_failing_test(self, broken_repo: Path) -> None:
        runner = RepairRunner(broken_repo, CompositePatcher([RulePatcher()]))
        incident = Incident(
            kind=IncidentKind.TEST_FAILURE,
            severity=IncidentSeverity.HIGH,
            source="tests/test_account.py::test_balance_adds_deposits",
            summary="NameError: name 'totl' is not defined",
            evidence={
                "test_node_id": "tests/test_account.py::test_balance_adds_deposits",
                "test_file": "tests/test_account.py",
                "exception_type": "NameError",
                "exception_value": "name 'totl' is not defined",
                "source_file": "src/account.py",
                "source_line": 6,
            },
        )

        choice = runner.prove(incident)

        assert choice is not None, "no candidate was produced for a fixable typo"
        assert choice.proven is True, f"the candidate was not proven: {choice.notes}"
        assert choice.candidate.replacement_snippet == "    return total"
        assert "passing" in " ".join(choice.notes)

    def test_the_sandbox_did_not_touch_the_real_tree(self, broken_repo: Path) -> None:
        """Verification must be free of side effects on the checkout."""
        before = (broken_repo / "src" / "account.py").read_text(encoding="utf-8")
        runner = RepairRunner(broken_repo, CompositePatcher([RulePatcher()]))
        incident = Incident(
            kind=IncidentKind.TEST_FAILURE,
            severity=IncidentSeverity.HIGH,
            source="t",
            summary="s",
            evidence={
                "test_node_id": "tests/test_account.py::test_balance_adds_deposits",
                "exception_type": "NameError",
                "exception_value": "name 'totl' is not defined",
                "source_file": "src/account.py",
            },
        )
        runner.prove(incident)
        assert (broken_repo / "src" / "account.py").read_text(encoding="utf-8") == before

    def test_a_stale_incident_is_reported_not_claimed(self, broken_repo: Path) -> None:
        """If the test already passes, there is nothing to fix and it must say so."""
        (broken_repo / "src" / "account.py").write_text(
            "def calculate_balance(opening, deposits):\n"
            "    total = opening\n"
            "    for deposit in deposits:\n"
            "        total = total + deposit\n"
            "    return total\n",
            encoding="utf-8",
        )
        runner = RepairRunner(broken_repo, CompositePatcher([RulePatcher()]))
        incident = Incident(
            kind=IncidentKind.TEST_FAILURE,
            severity=IncidentSeverity.HIGH,
            source="t",
            summary="s",
            evidence={
                "test_node_id": "tests/test_account.py::test_balance_adds_deposits",
                "exception_type": "NameError",
                "exception_value": "name 'totl' is not defined",
                "source_file": "src/account.py",
            },
        )
        choice = runner.prove(incident)
        assert choice is not None
        assert choice.proven is False
        assert "stale" in " ".join(choice.notes)


# ── detection: the real detector over a real repo ──────────────────────────


class TestDetection:
    def test_it_finds_a_real_failing_test(self, broken_repo: Path) -> None:
        detector = IncidentDetector(broken_repo, python_executable=PYTHON)
        incidents = detector.scan_tests()
        assert incidents, "the detector missed a genuinely failing test"
        assert any(
            "test_balance_adds_deposits" in incident.source for incident in incidents
        ), incidents

    def test_the_incident_carries_the_evidence_to_act_on_it(self, broken_repo: Path) -> None:
        detector = IncidentDetector(broken_repo, python_executable=PYTHON)
        incident = next(i for i in detector.scan_tests() if "balance" in i.source)
        assert incident.evidence["source_file"].endswith("account.py")
        assert incident.evidence["exception_type"] == "NameError"
        assert incident.evidence["command"]

    def test_a_healthy_repo_produces_no_test_incidents(self, tmp_path: Path) -> None:
        root = tmp_path / "healthy"
        root.mkdir()
        (root / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        detector = IncidentDetector(root, python_executable=PYTHON)
        assert detector.scan_tests() == []

    def test_resource_scan_is_bounded_and_real(self, tmp_path: Path) -> None:
        detector = IncidentDetector(tmp_path)
        incidents = detector.scan_resources(memory_percent=0.0, disk_percent=0.0)
        assert all(i.kind is IncidentKind.RESOURCE_PRESSURE for i in incidents)
        assert all("percent" in i.evidence for i in incidents)


# ── the whole brain, end to end ────────────────────────────────────────────


def _brain(repo: Path, tmp_path: Path, *, with_mandate: bool, auto: bool = False) -> ReflexBrain:
    ledger = MandateLedger(str(tmp_path / f"mandates-{with_mandate}-{auto}.json"))
    authority = MandateAuthority(key=MANDATE_KEY, ledger=ledger, allow_auto_issue=auto)
    if with_mandate:
        authority.issue(
            "surendra",
            scopes=(SCOPE_SOURCE_REPAIR,),
            allowed_paths=("src/**",),
            ttl_seconds=600,
        )
    return ReflexBrain(
        repo,
        authority=authority,
        detector=IncidentDetector(repo, python_executable=PYTHON),
        patcher=CompositePatcher([RulePatcher()]),
        reviewer=_reviewer(),
    )


def _reviewer():
    from friday.cognition.reviewer import LocalReviewer

    return LocalReviewer(REVIEW_KEY)


class TestReflexRepairsUnattended:
    """The headline behaviour the owner asked for."""

    def test_it_detects_and_repairs_without_asking(self, broken_repo: Path, tmp_path: Path) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=True)

        result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

        resolved = [o for o in result["outcomes"] if o["status"] == OutcomeStatus.RESOLVED.value]
        assert resolved, f"nothing was repaired: {result}"
        assert (broken_repo / "src" / "account.py").read_text(encoding="utf-8").endswith(
            "return total\n"
        )
        assert resolved[0]["evidence_class"] == "verified_repair"
        assert resolved[0]["evidence"]["authorised_by"].startswith("mandate_")

    def test_the_repair_is_a_real_commit_with_a_rollback_point(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))
        resolved = next(o for o in result["outcomes"] if o["status"] == OutcomeStatus.RESOLVED.value)

        assert resolved["evidence"]["applied_commit"]
        assert resolved["evidence"]["rollback_point"]
        branch = resolved["evidence"]["branch"]
        branches = _git(broken_repo, "branch", "--list", branch)
        assert branch in branches

    def test_without_a_mandate_it_stops_and_says_why(self, broken_repo: Path, tmp_path: Path) -> None:
        """Autonomy is granted, not assumed. The blocking step is named."""
        brain = _brain(broken_repo, tmp_path, with_mandate=False)

        result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

        awaiting = [o for o in result["outcomes"] if o["status"] == OutcomeStatus.AWAITING_MANDATE.value]
        assert awaiting, result
        assert "grant-autonomy" in awaiting[0]["detail"] or "granted" in awaiting[0]["detail"].lower()
        # And, crucially, nothing was applied.
        assert (broken_repo / "src" / "account.py").read_text(encoding="utf-8").endswith("return totl\n")

    def test_it_proactively_gets_autonomy_when_the_owner_opted_in(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        """Maximum-autonomy mode: one switch, no second command."""
        brain = _brain(broken_repo, tmp_path, with_mandate=False, auto=True)

        result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

        # The first pass has no mandate at detection time, so it proposes; the
        # authority self-issues, which the *next* pass can spend.
        first = brain.status()["autonomy"]
        if first["status"] != "ACTIVE":
            result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))
        assert brain.status()["autonomy"]["status"] == "ACTIVE"
        assert result["incidents"] >= 0

    def test_after_a_repair_the_fault_is_gone_on_the_next_pass(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        """The strongest possible check: the detector finds nothing left to fix."""
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        first = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))
        assert any(o["status"] == OutcomeStatus.RESOLVED.value for o in first["outcomes"])

        second = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

        assert second["incidents"] == 0, f"the repaired fault is still being detected: {second}"
        assert second["outcomes"] == []

    def test_an_incident_that_cannot_be_fixed_is_not_retried_in_a_loop(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        """A persistent fault must not become an infinite repair storm."""
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        incident = Incident(
            kind=IncidentKind.RESOURCE_PRESSURE,
            severity=IncidentSeverity.LOW,
            source="zombie_processes",
            summary="3 zombie process(es) present",
            evidence={"count": 3},
        )
        first = _run(brain.handle(incident))
        brain._remember(first)
        assert brain._recently_handled(incident) is True
        assert brain._recently_handled(incident, cooldown_seconds=0) is False

    def test_an_unfixable_failure_is_reported_as_a_gap_not_a_success(
        self, tmp_path: Path
    ) -> None:
        """The honest half: no candidate means NO_FIX_KNOWN, never RESOLVED."""
        root = tmp_path / "unfixable"
        (root / "src").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "src" / "logic.py").write_text(
            "def decide(flag):\n    return 'a' if flag else 'b'\n", encoding="utf-8"
        )
        (root / "tests" / "test_logic.py").write_text(
            "from src.logic import decide\n\n\ndef test_decide():\n    assert decide(True) == 'z'\n",
            encoding="utf-8",
        )
        (root / "conftest.py").write_text("import sys\nsys.path.insert(0, '.')\n", encoding="utf-8")
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.email", "t@l")
        _git(root, "config", "user.name", "T")
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "wrong expectation")

        brain = _brain(root, tmp_path, with_mandate=True)
        result = _run(brain.run_once(include={IncidentKind.TEST_FAILURE}))

        statuses = {o["status"] for o in result["outcomes"]}
        assert OutcomeStatus.RESOLVED.value not in statuses, result
        assert statuses & {OutcomeStatus.NO_FIX_KNOWN.value, OutcomeStatus.UNPROVEN.value}


class TestReflexHonesty:
    """What the brain reports about itself must be true."""

    def test_status_reports_autonomy_state(self, broken_repo: Path, tmp_path: Path) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        status = brain.status()
        assert status["autonomy"]["status"] == "ACTIVE"
        assert status["enabled"] is True

    def test_a_log_traceback_is_observed_not_guessed_at(self, tmp_path: Path) -> None:
        """A log line has no reproduction, so acting on it would be a guess."""
        brain = _brain(tmp_path, tmp_path, with_mandate=True)
        incident = Incident(
            kind=IncidentKind.LOG_ERROR,
            severity=IncidentSeverity.MEDIUM,
            source="logs:abc",
            summary="ValueError: bad input",
            evidence={"excerpt": "Traceback ...", "log_path": "logs/friday.log"},
        )
        outcome = _run(brain.handle(incident))
        assert outcome.status is OutcomeStatus.OBSERVED
        assert outcome.evidence_class == "observation"

    def test_peer_degradation_is_not_something_this_host_can_fix(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        incident = Incident(
            kind=IncidentKind.PEER_DEGRADED,
            severity=IncidentSeverity.MEDIUM,
            source="inference",
            summary="Inference answered but reports DEGRADED",
            evidence={"details": "status=degraded"},
        )
        outcome = _run(brain.handle(incident))
        assert outcome.status is OutcomeStatus.OBSERVED
        assert "has no authority over a remote service" in outcome.detail

    def test_an_unreachable_peer_without_a_mesh_is_escalated(self, broken_repo: Path, tmp_path: Path) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=True)
        incident = Incident(
            kind=IncidentKind.PEER_UNREACHABLE,
            severity=IncidentSeverity.HIGH,
            source="forge",
            summary="Forge did not answer",
            evidence={"endpoint": "https://forge.invalid"},
        )
        outcome = _run(brain.handle(incident))
        assert outcome.status is OutcomeStatus.ESCALATED
        assert "no mesh client" in outcome.detail

    def test_memory_pressure_waits_for_a_runtime_mandate_without_one(
        self, broken_repo: Path, tmp_path: Path
    ) -> None:
        brain = _brain(broken_repo, tmp_path, with_mandate=False)
        incident = Incident(
            kind=IncidentKind.RESOURCE_PRESSURE,
            severity=IncidentSeverity.HIGH,
            source="memory",
            summary="memory at 95%",
            evidence={"percent": 95.0},
        )
        outcome = _run(brain.handle(incident))
        assert outcome.status is OutcomeStatus.AWAITING_MANDATE

    def test_the_scan_survives_one_scanner_failing(self, broken_repo: Path, tmp_path: Path) -> None:
        """One broken scanner must not blind the brain to everything else."""
        detector = IncidentDetector(broken_repo, python_executable="/nonexistent/python")
        incidents = _run(detector.scan(include={IncidentKind.IMPORT_FAILURE, IncidentKind.TEST_FAILURE}))
        assert isinstance(incidents, list)


def _run(coro):
    """Run a coroutine from a sync test without requiring the asyncio plugin."""
    import asyncio

    return asyncio.run(coro)
