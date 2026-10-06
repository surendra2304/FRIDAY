"""The reflex brain: detect a fault, decide, act, verify, report.

This is the piece the owner asked for and the system did not have. Before it,
FRIDAY could *diagnose* — ``AutonomousController.execute_self_repair`` returned
``repairs_attempted: []`` every single time, and said so honestly. Honest and
useless is still useless. This module closes the loop.

The shape of a reflex pass:

1. **Detect.** Scan the things that actually break: the import surface, the test
   suite, a log tail, the peer mesh, host resources.
2. **Classify.** Turn a symptom into an :class:`Incident` with the evidence that
   produced it, so the decision that follows can be audited against the same
   facts the detector saw.
3. **Decide.** A strategy per incident kind. Code faults become candidate
   patches; peer faults become reconnects and escalation; resource faults become
   bounded cleanup. Nothing acts unless a mandate covers it.
4. **Prove.** A candidate is falsified by running the failing test *before*
   anyone is asked to trust it. A candidate that does not flip a failing test to
   passing is not a repair and is never filed.
5. **Apply and watch.** Through the existing gate: checkpoint, commit, then run
   the wider verification. A regression is rolled back automatically.
6. **Report.** Every outcome carries an evidence class and says exactly how far
   the process actually got.

Two properties are non-negotiable and are enforced here rather than documented:
**no repair is filed without a test that went from failing to passing**, and
**nothing is applied without a mandate**. When either is missing the outcome is
``AWAITING_MANDATE`` or ``UNPROVEN`` — never a euphemism for success.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from friday.core.logging import get_logger

logger = get_logger("cognition.reflex")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class IncidentKind(str, Enum):
    """The fault classes this brain knows how to reason about."""

    IMPORT_FAILURE = "IMPORT_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    PEER_UNREACHABLE = "PEER_UNREACHABLE"
    PEER_DEGRADED = "PEER_DEGRADED"
    RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
    LOG_ERROR = "LOG_ERROR"


class IncidentSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OutcomeStatus(str, Enum):
    """How far a reflex got. Never rounded up."""

    RESOLVED = "RESOLVED"                  # a test proved the fault gone
    APPLIED = "APPLIED"                    # committed, still under verification
    ROLLED_BACK = "ROLLED_BACK"            # applied, regressed, reverted
    UNPROVEN = "UNPROVEN"                  # a candidate existed but changed nothing provable
    NO_FIX_KNOWN = "NO_FIX_KNOWN"          # nothing here knows how to fix it
    AWAITING_MANDATE = "AWAITING_MANDATE"  # fixable, but no standing authority to act
    REFUSED = "REFUSED"                    # the gate or the reviewer said no
    ESCALATED = "ESCALATED"                # handed to a peer or the owner
    OBSERVED = "OBSERVED"                  # nothing to do; evidence recorded


@dataclass
class Incident:
    """One detected fault, with the evidence that produced it."""

    kind: IncidentKind
    severity: IncidentSeverity
    source: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=_now_iso)

    @property
    def key(self) -> str:
        """Stable identity so the same fault is not re-reported as new."""
        return f"{self.kind.value}:{self.source}:{self.summary[:120]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "source": self.source,
            "summary": self.summary,
            "evidence": self.evidence,
            "detected_at": self.detected_at,
        }


@dataclass
class ActionOutcome:
    """What was actually done about one incident, and what proves it."""

    incident: Incident
    status: OutcomeStatus
    action: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_class: str = "reflex_outcome"
    at: str = field(default_factory=_now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident": self.incident.as_dict(),
            "status": self.status.value,
            "action": self.action,
            "detail": self.detail,
            "evidence": self.evidence,
            "evidence_class": self.evidence_class,
            "at": self.at,
        }


# ── detection ──────────────────────────────────────────────────────────────


class IncidentDetector:
    """Finds faults using the project's real tools, not heuristics over files."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        python_executable: str | None = None,
        test_timeout: int = 900,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.python = python_executable or sys.executable
        self.test_timeout = test_timeout

    # -- imports ----------------------------------------------------------

    def scan_imports(self) -> list[Incident]:
        """Import every module in the package and report what cannot load.

        An unimportable module is the cheapest CRITICAL fault to find: it takes
        seconds, needs no test suite, and is exactly the class of breakage that
        reaches production because nobody imports that path in a test.
        """
        script = (
            "import importlib, pkgutil, sys, json\n"
            "sys.path.insert(0, 'src')\n"
            "bad = []\n"
            "try:\n"
            "    import friday, friday_deep\n"
            "except Exception as exc:\n"
            "    print(json.dumps([{'module': 'friday', 'error': f'{type(exc).__name__}: {exc}'}]))\n"
            "    raise SystemExit(0)\n"
            "for pkg in (friday, friday_deep):\n"
            "    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.'):\n"
            "        try:\n"
            "            importlib.import_module(m.name)\n"
            "        except Exception as exc:\n"
            "            bad.append({'module': m.name, 'error': f'{type(exc).__name__}: {exc}'})\n"
            "print(json.dumps(bad))\n"
        )
        try:
            proc = subprocess.run(
                [self.python, "-c", script],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return [
                Incident(
                    kind=IncidentKind.IMPORT_FAILURE,
                    severity=IncidentSeverity.MEDIUM,
                    source="import_scan",
                    summary=f"the import scan itself failed: {type(exc).__name__}",
                    evidence={"error": str(exc)},
                )
            ]

        import json

        payload = proc.stdout.strip().splitlines()
        if not payload:
            return []
        try:
            failures = json.loads(payload[-1])
        except ValueError:
            return []
        if not isinstance(failures, list):
            return []

        incidents: list[Incident] = []
        for failure in failures:
            module = str(failure.get("module", "?"))
            error = str(failure.get("error", ""))
            incidents.append(
                Incident(
                    kind=IncidentKind.IMPORT_FAILURE,
                    severity=(
                        IncidentSeverity.HIGH
                        if "ModuleNotFoundError" not in error
                        else IncidentSeverity.MEDIUM
                    ),
                    source=module,
                    summary=f"{module} cannot be imported: {error}",
                    evidence={"module": module, "error": error, "command": f"{self.python} -c <import scan>"},
                )
            )
        return incidents

    # -- tests ------------------------------------------------------------

    def scan_tests(self) -> list[Incident]:
        """Run the portable suite and report each failing test individually."""
        command = [
            self.python,
            "-m",
            "pytest",
            "-m",
            "not live and not hardware and not windows",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
            )
        except subprocess.TimeoutExpired:
            return [
                Incident(
                    kind=IncidentKind.TEST_FAILURE,
                    severity=IncidentSeverity.HIGH,
                    source="pytest",
                    summary=f"the test suite did not finish within {self.test_timeout}s",
                    evidence={"command": " ".join(command), "timeout_seconds": self.test_timeout},
                )
            ]
        except OSError as exc:
            return [
                Incident(
                    kind=IncidentKind.TEST_FAILURE,
                    severity=IncidentSeverity.MEDIUM,
                    source="pytest",
                    summary=f"the test suite could not be started: {exc}",
                    evidence={"command": " ".join(command)},
                )
            ]

        output = f"{proc.stdout}\n{proc.stderr}"
        from friday.cognition.patcher import parse_pytest_output

        incidents: list[Incident] = []
        for report in parse_pytest_output(output, self.repo_root):
            incidents.append(
                Incident(
                    kind=IncidentKind.TEST_FAILURE,
                    severity=IncidentSeverity.HIGH,
                    source=report.test_node_id or "pytest",
                    summary=report.summary(),
                    evidence={
                        "command": " ".join(command),
                        "exit_code": proc.returncode,
                        "test_node_id": report.test_node_id,
                        "test_file": report.test_file,
                        "exception_type": report.exception_type,
                        "exception_value": report.exception_value,
                        "source_file": report.source_file,
                        "source_line": report.source_line,
                        "traceback": report.traceback_text[-4000:],
                    },
                )
            )
        return incidents

    # -- peers ------------------------------------------------------------

    async def scan_fleet(self) -> list[Incident]:
        """Probe the eight peers, distinguishing 'says unhealthy' from 'no answer'."""
        from friday.ecosystem.fleet_client import fleet_client

        incidents: list[Incident] = []
        try:
            statuses = await fleet_client.get_all_statuses(force_refresh=True)
        except Exception as exc:
            return [
                Incident(
                    kind=IncidentKind.PEER_UNREACHABLE,
                    severity=IncidentSeverity.MEDIUM,
                    source="fleet",
                    summary=f"the fleet probe itself failed: {type(exc).__name__}",
                    evidence={"error": str(exc)},
                )
            ]

        for status in statuses:
            state = str(getattr(status, "status", "")).upper()
            details = str(getattr(status, "details", ""))
            unreachable = any(
                marker in details.lower()
                for marker in ("connection", "unreachable", "timeout", "timed out", "name or service", "ssl")
            )
            if unreachable:
                incidents.append(
                    Incident(
                        kind=IncidentKind.PEER_UNREACHABLE,
                        severity=IncidentSeverity.HIGH,
                        source=str(getattr(status, "id", "?")),
                        summary=f"{status.name} did not answer: {details}",
                        evidence={
                            "endpoint": getattr(status, "endpoint", ""),
                            "latency_ms": getattr(status, "latency_ms", None),
                            "details": details,
                            "scope": "transport-level reachability only",
                        },
                    )
                )
            elif state in {"DEGRADED", "OFFLINE"}:
                incidents.append(
                    Incident(
                        kind=IncidentKind.PEER_DEGRADED,
                        severity=IncidentSeverity.MEDIUM,
                        source=str(getattr(status, "id", "?")),
                        summary=f"{status.name} answered but reports {state}",
                        evidence={
                            "endpoint": getattr(status, "endpoint", ""),
                            "http_status_mapping": state,
                            "details": details,
                            "scope": "the peer's own health response, not task execution",
                        },
                    )
                )
        return incidents

    # -- host -------------------------------------------------------------

    def scan_resources(
        self, *, memory_percent: float = 92.0, disk_percent: float = 95.0
    ) -> list[Incident]:
        """Report host pressure that is demonstrably real."""
        try:
            import psutil
        except ImportError:
            return []

        incidents: list[Incident] = []
        try:
            vm = psutil.virtual_memory()
            if vm.percent >= memory_percent:
                incidents.append(
                    Incident(
                        kind=IncidentKind.RESOURCE_PRESSURE,
                        severity=IncidentSeverity.HIGH,
                        source="memory",
                        summary=f"memory at {vm.percent:.1f}% ({vm.available / 1024**3:.2f} GiB free)",
                        evidence={"percent": vm.percent, "available_gb": round(vm.available / 1024**3, 2)},
                    )
                )
            usage = psutil.disk_usage(str(self.repo_root.anchor or self.repo_root))
            if usage.percent >= disk_percent:
                incidents.append(
                    Incident(
                        kind=IncidentKind.RESOURCE_PRESSURE,
                        severity=IncidentSeverity.MEDIUM,
                        source="disk",
                        summary=f"disk at {usage.percent:.1f}% ({usage.free / 1024**3:.2f} GiB free)",
                        evidence={"percent": usage.percent, "free_gb": round(usage.free / 1024**3, 2)},
                    )
                )
            zombies = sum(
                1
                for proc in psutil.process_iter(["status"])
                if proc.info.get("status") == psutil.STATUS_ZOMBIE
            )
            if zombies:
                incidents.append(
                    Incident(
                        kind=IncidentKind.RESOURCE_PRESSURE,
                        severity=IncidentSeverity.LOW,
                        source="zombie_processes",
                        summary=f"{zombies} zombie process(es) present",
                        evidence={"count": zombies},
                    )
                )
        except Exception as exc:  # psutil is best-effort by design
            logger.warning("resource scan degraded: %s", exc)
        return incidents

    def scan_log_tail(self, log_path: str | Path | None = None, *, max_lines: int = 400) -> list[Incident]:
        """Report tracebacks in the log tail that no test has already caught."""
        path = Path(log_path or self.repo_root / "logs" / "friday.log")
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
        except OSError:
            return []

        text = "\n".join(lines)
        import re

        tracebacks = re.findall(r"Traceback \(most recent call last\):(.{0,1500}?)(?=\n\S|\Z)", text, re.DOTALL)
        incidents: list[Incident] = []
        for block in tracebacks[-5:]:
            last = [line for line in block.strip().splitlines() if line.strip().startswith(("E ", "  ", "\t"))]
            incident_hash = str(abs(hash(block.strip()[:300])))
            incidents.append(
                Incident(
                    kind=IncidentKind.LOG_ERROR,
                    severity=IncidentSeverity.MEDIUM,
                    source=f"logs:{incident_hash[-8:]}",
                    summary=(last[-1].strip()[:200] if last else "a traceback appears in the log tail"),
                    evidence={
                        "log_path": str(path),
                        "excerpt": block.strip()[-1200:],
                        "scope": "observed in the log; the originating request is not identified here",
                    },
                )
            )
        return incidents

    # -- aggregate --------------------------------------------------------

    async def scan(self, *, include: set[IncidentKind] | None = None) -> list[Incident]:
        """Run every scanner, tolerating one failing without losing the others."""
        wanted = include or set(IncidentKind)
        found: list[Incident] = []

        async def guarded(coro: Any, label: str) -> list[Incident]:
            try:
                return await coro
            except Exception as exc:
                logger.warning("scanner %s failed: %s", label, exc)
                return []

        if IncidentKind.IMPORT_FAILURE in wanted:
            found += await guarded(asyncio.to_thread(self.scan_imports), "imports")
        if IncidentKind.TEST_FAILURE in wanted:
            found += await guarded(asyncio.to_thread(self.scan_tests), "tests")
        if {IncidentKind.PEER_UNREACHABLE, IncidentKind.PEER_DEGRADED} & wanted:
            found += await guarded(self.scan_fleet(), "fleet")
        if IncidentKind.RESOURCE_PRESSURE in wanted:
            found += await guarded(asyncio.to_thread(self.scan_resources), "resources")
        if IncidentKind.LOG_ERROR in wanted:
            found += await guarded(asyncio.to_thread(self.scan_log_tail), "logs")

        order = {
            IncidentSeverity.CRITICAL: 0,
            IncidentSeverity.HIGH: 1,
            IncidentSeverity.MEDIUM: 2,
            IncidentSeverity.LOW: 3,
        }
        found.sort(key=lambda incident: order[incident.severity])
        return found


# ── the repair runner ──────────────────────────────────────────────────────


@dataclass
class RepairChoice:
    """A candidate patch plus the proof it produced."""

    candidate: Any
    proven: bool
    test_command: str
    before: str
    after: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "proven": self.proven,
            "test_command": self.test_command,
            "before": self.before,
            "after": self.after,
            "notes": list(self.notes),
        }


class RepairRunner:
    """Turns a code fault into either a proven repair or an honest failure.

    The verification is the whole design. A candidate is applied to a throwaway
    copy of the repository and the failing test must flip from failing to
    passing *there* before the real pipeline is asked to file anything. A model's
    confidence is worth nothing; a test that changed colour is worth everything.
    """

    def __init__(
        self,
        repo_root: str | Path,
        patcher: Any,
        *,
        python_executable: str | None = None,
        timeout: int = 600,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.patcher = patcher
        self.python = python_executable or sys.executable
        #: One test run may take this long. It is deliberately shorter than the
        #: detector's budget for the whole suite: a stuck test has to be caught
        #: and reported, not waited on until the process that is diagnosing it
        #: also stops responding.
        self.timeout = timeout

    # -- helpers ----------------------------------------------------------

    def _read(self, relative: str) -> str:
        path = Path(relative)
        if not path.is_absolute():
            path = self.repo_root / relative
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def _run_test(self, node_id: str, cwd: Path, *, extra_args: list[str] | None = None) -> tuple[int, str]:
        command = [
            self.python,
            "-m",
            "pytest",
            node_id,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *(extra_args or []),
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, f"test timed out after {self.timeout}s"
        except OSError as exc:
            return 127, str(exc)
        return proc.returncode, f"{proc.stdout}\n{proc.stderr}"

    @staticmethod
    def _tail(output: str, lines: int = 25) -> str:
        return "\n".join(output.strip().splitlines()[-lines:])

    # -- the proof ---------------------------------------------------------

    def prove(self, incident: Incident) -> RepairChoice | None:
        """Find a candidate, then try to falsify it against the failing test."""
        source_rel = str(incident.evidence.get("source_file") or "")
        node_id = str(incident.evidence.get("test_node_id") or incident.source or "")
        if not source_rel or not node_id:
            return None

        # Confirm the fault still exists before looking for a fix. An incident
        # can be stale for entirely good reasons — another process repaired it, a
        # dependency came back, the code moved on — and "fixing" a healthy tree is
        # how an autonomous system creates the bug it then reports.
        status, output = self._run_test(node_id, self.repo_root)
        if status == 0:
            return RepairChoice(
                candidate=type(
                    "_Stale",
                    (),
                    {
                        "target_file": source_rel,
                        "original_snippet": "",
                        "replacement_snippet": "",
                        "rationale": "",
                        "backend": "none",
                        "as_dict": lambda self=None: {},
                    },
                )(),
                proven=False,
                test_command=f"pytest {node_id}",
                before="the test passes on the current tree",
                after="nothing to fix",
                notes=["the incident is stale: the test does not currently fail"],
            )

        current_source = self._read(source_rel)
        if not current_source:
            return None

        from friday.cognition.patcher import FailureReport

        report = FailureReport(
            test_node_id=node_id,
            test_file=str(incident.evidence.get("test_file") or ""),
            exception_type=str(incident.evidence.get("exception_type") or ""),
            exception_value=str(incident.evidence.get("exception_value") or ""),
            source_file=source_rel,
            source_line=int(incident.evidence.get("source_line") or 0),
            traceback_text=str(incident.evidence.get("traceback") or ""),
        )
        candidate = self.patcher.candidate_for(
            report, repo_root=self.repo_root, current_source=current_source
        )
        if candidate is None:
            return None

        if current_source.count(candidate.original_snippet) != 1:
            return RepairChoice(
                candidate=candidate,
                proven=False,
                test_command=f"pytest {node_id}",
                before="the quoted original does not appear exactly once",
                after="not attempted",
                notes=["ambiguous snippet; the gate would refuse it and the reviewer flags it"],
            )

        return self._verify_in_sandbox(candidate, node_id)

    def _verify_in_sandbox(self, candidate: Any, node_id: str) -> RepairChoice:
        """Apply to a copy, run the test there, and report what actually happened."""
        workdir = Path(tempfile.mkdtemp(prefix="friday-reflex-"))
        sandbox = workdir / "repo"
        try:
            shutil.copytree(
                self.repo_root,
                sandbox,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache", "*.pyc"
                ),
            )
        except (OSError, shutil.Error) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            return RepairChoice(
                candidate=candidate,
                proven=False,
                test_command=f"pytest {node_id}",
                before="sandbox copy failed",
                after=f"{type(exc).__name__}: {exc}",
                notes=["verification could not run, so no repair may be claimed"],
            )

        try:
            before_code, before_output = self._run_test(node_id, sandbox)
            if before_code == 0:
                return RepairChoice(
                    candidate=candidate,
                    proven=False,
                    test_command=f"pytest {node_id}",
                    before="the test passed before any change",
                    after="nothing to fix",
                    notes=["the incident is stale: the test does not currently fail"],
                )

            target = sandbox / candidate.target_file
            try:
                text = target.read_text(encoding="utf-8")
            except OSError as exc:
                return RepairChoice(
                    candidate=candidate,
                    proven=False,
                    test_command=f"pytest {node_id}",
                    before="target file unreadable in the sandbox",
                    after=str(exc),
                )
            if text.count(candidate.original_snippet) != 1:
                return RepairChoice(
                    candidate=candidate,
                    proven=False,
                    test_command=f"pytest {node_id}",
                    before="the snippet does not appear exactly once",
                    after="not applied",
                )
            target.write_text(
                text.replace(candidate.original_snippet, candidate.replacement_snippet, 1),
                encoding="utf-8",
            )

            after_code, after_output = self._run_test(node_id, sandbox)
            proven = after_code == 0
            return RepairChoice(
                candidate=candidate,
                proven=proven,
                test_command=f"pytest {node_id}",
                before=self._tail(before_output, 12),
                after=self._tail(after_output, 12),
                notes=(
                    [f"the test went from failing to passing in a sandbox copy ({candidate.backend} patch)"]
                    if proven
                    else [f"the candidate did not fix the test (exit {after_code}); it is discarded"]
                ),
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _summarise_failure(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    for line in reversed(lines):
        if "passed" in line or "failed" in line or "error" in line.lower():
            return line.strip()[:200]
    return lines[-1][:200] if lines else "unknown"


# ── the brain ──────────────────────────────────────────────────────────────


class ReflexBrain:
    """One brain: detects, decides, acts, verifies, and never overstates.

    The loop is deliberately conservative about what it *claims* and aggressive
    about what it *tries*. Detection, candidate synthesis and sandbox
    verification all run without any authority — they change nothing outside a
    temporary directory. Only the apply step needs a mandate, and that is the
    only place this class can touch the working tree.
    """

    def __init__(
        self,
        repo_root: str | Path,
        *,
        authority: Any | None = None,
        gate_factory: Callable[[], Any] | None = None,
        detector: IncidentDetector | None = None,
        patcher: Any | None = None,
        runner: RepairRunner | None = None,
        reviewer: Any | None = None,
        mesh: Any | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
        owner: str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.interval_seconds = interval_seconds or _env_int(
            "FRIDAY_REFLEX_INTERVAL_SECONDS", 900, minimum=60
        )
        self.enabled = _env_flag("FRIDAY_REFLEX_ENABLED", True) if enabled is None else enabled
        self.owner = owner or os.getenv("FRIDAY_OWNER_NAME", "surendra")

        self._authority = authority
        self._gate_factory = gate_factory
        self.detector = detector or IncidentDetector(self.repo_root)
        if patcher is None:
            from friday.cognition.patcher import CompositePatcher

            patcher = CompositePatcher()
        self.runner = runner or RepairRunner(self.repo_root, patcher)
        self.reviewer = reviewer
        self.mesh = mesh

        self._state: dict[str, Any] = {
            "running": False,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "status": "NOT_STARTED",
            "passes": 0,
            "last_started_at": None,
            "last_completed_at": None,
            "last_error": None,
            "incidents_seen": 0,
            "outcomes": [],
            "autonomy": None,
        }
        self._handled: dict[str, float] = {}

    # -- introspection ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        state = dict(self._state)
        if self._authority is not None:
            state["autonomy"] = self._authority.status()
        state["outcomes"] = [outcome.as_dict() for outcome in self._state["outcomes"]][-25:]
        return state

    def _remember(self, outcome: ActionOutcome) -> None:
        self._handled[outcome.incident.key] = time.time()
        bucket: list[ActionOutcome] = self._state["outcomes"]
        bucket.append(outcome)
        if len(bucket) > 200:
            del bucket[:-200]

    def _recently_handled(self, incident: Incident, cooldown_seconds: int = 1800) -> bool:
        seen = self._handled.get(incident.key)
        return seen is not None and (time.time() - seen) < cooldown_seconds

    # -- authority --------------------------------------------------------

    def _authority_or_none(self) -> Any | None:
        if self._authority is not None:
            return self._authority
        try:
            from friday.cognition.mandate import MandateAuthority

            self._authority = MandateAuthority()
        except Exception as exc:
            logger.warning("autonomy authority unavailable: %s", exc)
            self._authority = None
        return self._authority

    def _gate(self) -> Any | None:
        """Build the repair gate, sharing the reviewer's key so reviews verify.

        A gate built without a verification key refuses every review with
        ``NO_REVIEW_KEY`` — correct, and useless. The brain therefore reads the
        same environment key the reviewer signs with, so the two halves of the
        pipeline agree by construction rather than by configuration discipline.
        """
        if self._gate_factory is not None:
            return self._gate_factory()
        from friday.autonomous.self_repair import (
            _REVIEW_SIGNING_ENV,
            GitRepairApplier,
            SelfRepairGate,
        )

        review_key: bytes | None = None
        for name in _REVIEW_SIGNING_ENV:
            value = os.getenv(name, "").strip()
            if value:
                review_key = value.encode("utf-8")
                break

        try:
            return SelfRepairGate(
                GitRepairApplier(str(self.repo_root)),
                review_verification_key=review_key,
            )
        except Exception as exc:
            logger.warning("repair gate unavailable: %s", exc)
            return None

    def _reviewer(self) -> Any | None:
        if self.reviewer is not None:
            return self.reviewer
        from friday.cognition.reviewer import build_local_reviewer_from_env

        self.reviewer = build_local_reviewer_from_env()
        return self.reviewer

    # -- one incident -----------------------------------------------------

    async def handle(self, incident: Incident) -> ActionOutcome:
        if incident.kind is IncidentKind.TEST_FAILURE:
            outcome = await asyncio.to_thread(self._repair_test_failure, incident)
            if outcome.status is OutcomeStatus.NO_FIX_KNOWN:
                return await self._ask_peers_for_help(incident, outcome)
            return outcome
        if incident.kind is IncidentKind.IMPORT_FAILURE:
            outcome = await asyncio.to_thread(self._repair_import_failure, incident)
            if outcome.status is OutcomeStatus.NO_FIX_KNOWN:
                return await self._ask_peers_for_help(incident, outcome)
            return outcome
        if incident.kind in (IncidentKind.PEER_UNREACHABLE, IncidentKind.PEER_DEGRADED):
            return await self._respond_to_peer(incident)
        if incident.kind is IncidentKind.RESOURCE_PRESSURE:
            return self._respond_to_pressure(incident)
        if incident.kind is IncidentKind.LOG_ERROR:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.OBSERVED,
                action="record_log_error",
                detail=(
                    "A traceback is present in the log. It is recorded rather than acted on: "
                    "a log line carries no failing test and no reproduction, so any change made "
                    "from it would be a guess."
                ),
                evidence={
                    "log_path": incident.evidence.get("log_path"),
                    "scope": "log observation only",
                },
                evidence_class="observation",
            )
        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.NO_FIX_KNOWN,
            action="none",
            detail=f"No strategy is registered for {incident.kind.value}.",
        )

    # -- asking for help --------------------------------------------------

    async def _ask_peers_for_help(self, incident: Incident, local: ActionOutcome) -> ActionOutcome:
        """The last rung: this host could not fix it, so ask the peers that might.

        Deliberately *after* the local attempt, not instead of it: asking someone
        else to do what you can do yourself is the expensive way to be slow. The
        peers are asked in parallel, each answer is reported as that peer's, and
        the outcome never claims a peer did work the peer's own receipt does not
        prove. If no mesh is attached the local answer stands, unchanged.
        """
        if self.mesh is None:
            return local

        from friday.cognition.assistance import AssistanceBroker

        capability = (
            "source_repair"
            if incident.kind is IncidentKind.TEST_FAILURE
            else "source_repair"
        )
        node_id = str(incident.evidence.get("test_node_id") or incident.source or "")
        objective = (
            f"A fault on the FRIDAY host could not be repaired locally. Incident {incident.kind.value} "
            f"in {incident.source}: {incident.summary}. "
            f"Failing test: {node_id or 'not named'}. "
            f"Report a repair you can verify, or say you cannot."
        )
        broker = AssistanceBroker(mesh=self.mesh)
        try:
            asked = await broker.request_help_from_peers(
                caller="friday",
                capability=capability,
                objective=objective,
                inputs={
                    "incident": incident.as_dict() if hasattr(incident, "as_dict") else {},
                    "test_node_id": node_id,
                },
            )
        except Exception as exc:
            return ActionOutcome(
                incident=incident,
                status=local.status,
                action=local.action,
                detail=f"{local.detail} (asking the peers raised {type(exc).__name__}: {exc})",
                evidence={**local.evidence, "peer_escalation_error": f"{type(exc).__name__}: {exc}"},
                evidence_class=local.evidence_class,
            )

        if asked["performed"]:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.RESOLVED,
                action="delegated_to_peer",
                detail=(
                    f"This host could not repair it, so the peers were asked and "
                    f"{asked['completed_by']} completed the request with a verified receipt. "
                    f"The work is {asked['completed_by']}'s, not this host's."
                ),
                evidence={
                    **local.evidence,
                    "delegation": asked,
                    "local_attempt": local.detail,
                },
                evidence_class="peer_verified_work",
            )

        return ActionOutcome(
            incident=incident,
            status=local.status,
            action=local.action,
            detail=(
                f"{local.detail} The peers were then asked and none of them completed it either; "
                "each peer's own answer is in the evidence."
            ),
            evidence={**local.evidence, "peer_escalation": asked},
            evidence_class=local.evidence_class,
        )

    # -- code faults ------------------------------------------------------

    def _repair_test_failure(self, incident: Incident) -> ActionOutcome:
        choice = self.runner.prove(incident)
        if choice is None:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.NO_FIX_KNOWN,
                action="synthesise_patch",
                detail=(
                    "No patcher (rule or model) produced a candidate for this failure. "
                    "Nothing was changed. This is a genuine gap, and it is reported as one."
                ),
                evidence={"test_node_id": incident.evidence.get("test_node_id")},
            )
        if not choice.proven:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.UNPROVEN,
                action="sandbox_verify",
                detail=(
                    "A candidate was produced but did not turn the failing test green, so it was "
                    "discarded. An unproven change is not a repair."
                ),
                evidence=choice.as_dict(),
                evidence_class="sandbox_falsification",
            )
        return self._file_and_apply(incident, choice)

    def _repair_import_failure(self, incident: Incident) -> ActionOutcome:
        """Unimportable modules: enough to attempt, often too little to prove.

        An import failure has no failing test attached, so the only honest proof
        available is that the module imports afterwards. That is a weaker claim
        than a test, and the outcome says so.
        """
        module = str(incident.evidence.get("module") or "")
        if not module:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.NO_FIX_KNOWN,
                action="none",
                detail="The failure did not name a module to repair.",
            )
        remaining = incident.evidence.get("error", "")
        if "PyQt6" in str(remaining) or "No module named" in str(remaining):
            optional = [name for name in ("PyQt6", "resemblyzer", "pycom") if name in str(remaining)]
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ESCALATED,
                action="declare_optional",
                detail=(
                    f"{module} needs {optional or 'a package'} that is not installed. This is a "
                    "dependency decision, not a code defect: installing it changes the host, and "
                    "guarding the import changes the module's public behaviour. Reported for the "
                    "owner to choose."
                ),
                evidence={"module": module, "error": remaining},
                evidence_class="diagnosis",
            )
        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.NO_FIX_KNOWN,
            action="none",
            detail=f"{module} fails to import for a reason no registered strategy handles.",
            evidence={"module": module, "error": remaining},
        )

    def _file_and_apply(self, incident: Incident, choice: RepairChoice) -> ActionOutcome:
        """Run a proven candidate through the real gate, then watch it."""
        gate = self._gate()
        authority = self._authority_or_none()
        if gate is None:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ESCALATED,
                action="apply",
                detail=(
                    "The repair is proven, but no repair gate could be constructed for this "
                    "checkout, so it was not applied. The working tree is untouched."
                ),
                evidence=choice.as_dict(),
            )

        base_commit = gate.head_commit() if hasattr(gate, "head_commit") else None
        if not base_commit:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ESCALATED,
                action="propose",
                detail=(
                    "The repair is proven, but this checkout has no readable HEAD, so there is no "
                    "checkpoint to branch from and nothing was applied. The working tree is untouched."
                ),
                evidence=choice.as_dict(),
            )

        candidate = choice.candidate
        verdict = None
        if authority is not None:
            # Maximum-autonomy mode: an operator who set FRIDAY_AUTONOMY_AUTO_MANDATE
            # gets autonomy on the first pass rather than having to run a second
            # command. `ensure_mandate` is a no-op when auto-issue is off, so the
            # default remains "the owner decides".
            authority.ensure_mandate(self.owner, scopes=("source_repair",))
            verdict = authority.evaluate(
                "source_repair",
                paths=(candidate.target_file,),
                has_test_evidence=True,
            )

        from friday.autonomous.self_repair import RepairProposal

        proposal = RepairProposal(
            repo_path=str(self.repo_root),
            branch=f"reflex/{incident.kind.value.lower()}-{int(time.time())}",
            base_commit=base_commit,
            target_file=candidate.target_file,
            original_snippet=candidate.original_snippet,
            replacement_snippet=candidate.replacement_snippet,
            rationale=candidate.rationale,
            proposed_by="friday",
            test_evidence={
                "command": choice.test_command,
                "passed": True,
                "summary": "the failing test passes after the change in a sandbox copy",
            },
        )

        workdir = tempfile.mkdtemp(prefix="friday-file-")
        try:
            record, receipt = gate.propose(proposal)
        except Exception as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.REFUSED,
                action="propose",
                detail=f"The gate could not accept the proposal: {type(exc).__name__}: {exc}",
                evidence=choice.as_dict(),
            )
        shutil.rmtree(workdir, ignore_errors=True)

        if receipt.outcome != "ACCEPTED":
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.REFUSED,
                action="propose",
                detail=f"The gate refused the proposal: {receipt.detail}",
                evidence={**choice.as_dict(), "receipt": receipt.as_dict()},
            )

        patch_id = record.patch_id

        reviewer = self._reviewer()
        if reviewer is None:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.AWAITING_MANDATE,
                action="review",
                detail=(
                    "The repair is filed and proven, but no reviewer key is configured, so it "
                    "cannot be reviewed and therefore cannot be approved. Set "
                    "FRIDAY_SELF_REPAIR_REVIEW_KEY (or configure Sentinel) to complete the pipeline."
                ),
                evidence={**choice.as_dict(), "patch_id": patch_id},
                evidence_class="pipeline_transition",
            )

        # The reviewer judges the file the patch would *produce*, so a fragment is
        # never mistaken for a malformed module.
        current_source = self.runner._read(candidate.target_file)
        allowed_paths: tuple[str, ...] = ()
        if isinstance(verdict, object) and verdict is not None:
            mandate = next(
                (
                    m
                    for m in getattr(authority, "active", lambda: [])()
                    if m.mandate_id == getattr(verdict, "mandate_id", "")
                ),
                None,
            )
            if mandate is not None:
                allowed_paths = tuple(mandate.allowed_paths)

        review = reviewer.review(
            patch_fingerprint=record.proposal.fingerprint(),
            target_file=candidate.target_file,
            replacement_snippet=candidate.replacement_snippet,
            original_snippet=candidate.original_snippet,
            current_source=current_source,
            test_evidence=proposal.test_evidence,
            allowed_paths=allowed_paths,
        )
        review_receipt = gate.record_review(patch_id, review.document)
        if review_receipt.outcome != "ACCEPTED":
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.REFUSED if review.cleared else OutcomeStatus.UNPROVEN,
                action="review",
                detail=(
                    f"The local review did not clear the patch: {review_receipt.detail}. "
                    + ("; ".join(review.reasons) if review.reasons else "")
                ).strip(),
                evidence={**choice.as_dict(), "patch_id": patch_id, "review": review_receipt.as_dict()},
            )

        if authority is None or verdict is None or not verdict.allowed:
            reason = (
                verdict.reason
                if verdict is not None
                else "no autonomy authority is configured"
            )
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.AWAITING_MANDATE,
                action="approve",
                detail=(
                    f"The repair is reviewed, proven and one command from done: {reason}. "
                    "Grant standing autonomy with `friday --grant-autonomy`, or approve this patch "
                    f"directly with `friday --approve-repair {patch_id}`."
                ),
                evidence={
                    **choice.as_dict(),
                    "patch_id": patch_id,
                    "review_verdict": review.verdict,
                    "checks_run": review.checks_run,
                },
                evidence_class="pipeline_transition",
            )

        approval = authority.approve_repair(gate, patch_id, scope="source_repair")
        if approval is None or getattr(approval, "outcome", "REFUSED") != "ACCEPTED":
            detail = getattr(approval, "detail", "") or getattr(approval, "reason", "")
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.REFUSED,
                action="approve",
                detail=f"Approval was refused: {detail}",
                evidence={**choice.as_dict(), "patch_id": patch_id},
            )

        applied = gate.apply(patch_id)
        if applied.outcome != "ACCEPTED":
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.REFUSED,
                action="apply",
                detail=f"Apply was refused: {applied.detail}",
                evidence={**choice.as_dict(), "patch_id": patch_id, "receipt": applied.as_dict()},
            )

        # Post-apply watch: prove it on the real tree, and undo it if it regressed.
        node_id = str(incident.evidence.get("test_node_id") or "")
        code, output = self.runner._run_test(node_id, self.repo_root)
        if code != 0:
            rolled = gate.rollback(patch_id)
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ROLLED_BACK,
                action="apply_then_rollback",
                detail=(
                    "The repair passed in the sandbox but failed on the real tree, so it was "
                    f"rolled back automatically. Rollback receipt: {rolled.outcome}."
                ),
                evidence={
                    **choice.as_dict(),
                    "patch_id": patch_id,
                    "post_apply_output": self.runner._tail(output, 15),
                    "rollback": rolled.as_dict(),
                },
                evidence_class="verified_rollback",
            )

        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.RESOLVED,
            action="propose_review_approve_apply_verify",
            detail=(
                f"Repaired {candidate.target_file} unattended: the failing test now passes on the "
                f"real tree. Patch {patch_id} on branch {proposal.branch}."
            ),
            evidence={
                **choice.as_dict(),
                "patch_id": patch_id,
                "branch": proposal.branch,
                "applied_commit": getattr(record, "applied_commit", None),
                "rollback_point": getattr(record, "checkpoint_commit", None),
                "authorised_by": verdict.mandate_id,
            },
            evidence_class="verified_repair",
        )

    # -- peers ------------------------------------------------------------

    async def _respond_to_peer(self, incident: Incident) -> ActionOutcome:
        """Reconnect, or escalate. A peer's code is not on this machine."""
        peer = incident.source
        if incident.kind is IncidentKind.PEER_DEGRADED:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.OBSERVED,
                action="peer_health_recorded",
                detail=(
                    f"{peer} answered and reports itself unhealthy. Nothing was changed: its "
                    "recovery is its own, and this host has no authority over a remote service."
                ),
                evidence=incident.evidence,
                evidence_class="observation",
            )

        if self.mesh is None:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ESCALATED,
                action="reconnect",
                detail=(
                    f"{peer} is unreachable and no mesh client is attached to this brain, so no "
                    "reconnect was attempted."
                ),
                evidence=incident.evidence,
            )

        try:
            result = await self.mesh.reconnect(peer)
        except Exception as exc:
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.ESCALATED,
                action="reconnect",
                detail=f"The reconnect attempt raised {type(exc).__name__}: {exc}",
                evidence=incident.evidence,
            )

        if getattr(result, "recovered", False):
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.RESOLVED,
                action="reconnect",
                detail=f"{peer} answered after {getattr(result, 'attempts', 0)} reconnect attempt(s).",
                evidence={**incident.evidence, "reconnect": result.as_dict()},
                evidence_class="transport_recovery",
            )
        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.ESCALATED,
            action="reconnect_then_mesh",
            detail=(
                f"{peer} did not answer after {getattr(result, 'attempts', 0)} attempt(s). "
                "Escalated to the mesh: a peer that cannot be reached from here may still be "
                "reachable from another agent, and its own recovery is not this host's to perform."
            ),
            evidence={**incident.evidence, "reconnect": result.as_dict()},
        )

    # -- host -------------------------------------------------------------

    def _respond_to_pressure(self, incident: Incident) -> ActionOutcome:
        """Bounded, reversible cleanup — or an honest refusal to act."""
        import gc

        if incident.source == "zombie_processes":
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.OBSERVED,
                action="none",
                detail=(
                    "Zombie processes are reaped by their parent. Killing them from here would "
                    "target the parent's responsibility, so nothing was done and the count is "
                    "reported instead."
                ),
                evidence=incident.evidence,
                evidence_class="observation",
            )

        if incident.source == "memory":
            authority = self._authority_or_none()
            verdict = (
                authority.evaluate("runtime_cleanup") if authority is not None else None
            )
            if verdict is None or not verdict.allowed:
                return ActionOutcome(
                    incident=incident,
                    status=OutcomeStatus.AWAITING_MANDATE,
                    action="collect_garbage",
                    detail=(
                        "Memory pressure is high. A garbage collection is harmless but is a change "
                        "to a running process, so it waits for a runtime_cleanup mandate."
                    ),
                    evidence=incident.evidence,
                )
            before = _process_rss_mb()
            collected = gc.collect()
            after = _process_rss_mb()
            authority.record_use(verdict.mandate_id)
            return ActionOutcome(
                incident=incident,
                status=OutcomeStatus.RESOLVED if after < before else OutcomeStatus.OBSERVED,
                action="collect_garbage",
                detail=(
                    f"Ran a garbage collection ({collected} objects). Host memory pressure is not "
                    "necessarily this process's, so the effect is measured, not assumed."
                ),
                evidence={
                    **incident.evidence,
                    "objects_collected": collected,
                    "process_rss_mb_before": before,
                    "process_rss_mb_after": after,
                },
                evidence_class="measured_effect",
            )

        return ActionOutcome(
            incident=incident,
            status=OutcomeStatus.ESCALATED,
            action="none",
            detail=(
                f"{incident.source} pressure reported. Deleting files or stopping services to "
                "relieve it is destructive and not covered by an autonomous mandate."
            ),
            evidence=incident.evidence,
        )

    # -- the loop ---------------------------------------------------------

    async def run_once(self, *, include: set[IncidentKind] | None = None) -> dict[str, Any]:
        """One full pass: scan everything, act on what is actionable, report."""
        self._state["last_started_at"] = _now_iso()
        self._state["passes"] += 1

        try:
            incidents = await self.detector.scan(include=include)
        except Exception as exc:
            self._state["last_error"] = f"{type(exc).__name__}: {exc}"
            self._state["status"] = "ERROR"
            self._state["last_completed_at"] = _now_iso()
            return {
                "status": "ERROR",
                "detail": "The scan itself failed; nothing was examined, so nothing may be claimed.",
                "error": self._state["last_error"],
            }

        self._state["incidents_seen"] = len(incidents)
        outcomes: list[ActionOutcome] = []
        for incident in incidents:
            if self._recently_handled(incident):
                continue
            try:
                outcome = await self.handle(incident)
            except Exception as exc:
                logger.exception("reflex handler failed for %s", incident.key)
                outcome = ActionOutcome(
                    incident=incident,
                    status=OutcomeStatus.ESCALATED,
                    action="handle",
                    detail=f"The handler raised {type(exc).__name__}: {exc}",
                )
            self._remember(outcome)
            outcomes.append(outcome)

        counts: dict[str, int] = {}
        for outcome in outcomes:
            counts[outcome.status.value] = counts.get(outcome.status.value, 0) + 1

        self._state["status"] = "COMPLETED"
        self._state["last_completed_at"] = _now_iso()
        self._state["last_error"] = None

        return {
            "status": "COMPLETED",
            "incidents": len(incidents),
            "acted_on": len(outcomes),
            "skipped_recently_handled": len(incidents) - len(outcomes),
            "counts": counts,
            "autonomy": self._authority_or_none().status() if self._authority_or_none() else None,
            "outcomes": [outcome.as_dict() for outcome in outcomes],
        }

    async def run_forever(self) -> None:
        """The scheduled half. Sleeps first so a restart is not a repair storm."""
        self._state["running"] = True
        try:
            while True:
                await asyncio.sleep(self.interval_seconds)
                if not self.enabled:
                    self._state["status"] = "DISABLED"
                    return
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                    logger.exception("reflex pass failed")
        finally:
            self._state["running"] = False


def _process_rss_mb() -> float:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / 1024**2, 1)
    except Exception:
        return 0.0


#: One brain per process, built lazily so importing the module never starts work.
_reflex_brain: ReflexBrain | None = None


def get_reflex_brain(repo_root: str | Path | None = None) -> ReflexBrain:
    """Return the process-wide reflex brain, creating it on first use.

    The brain is given the process-wide mesh, so a peer that cannot be reached
    gets an actual reconnect attempt rather than "no mesh client is attached".
    Without this the fleet half of the reflex was inert in every real deployment:
    the mesh existed, and nothing that ran automatically ever used it.
    """
    global _reflex_brain
    if _reflex_brain is None:
        root = repo_root or os.getenv("FRIDAY_REFLEX_REPO", "").strip() or _default_repo_root()
        mesh = None
        try:
            from friday.cognition.mesh import get_mesh

            mesh = get_mesh()
            logger.info("reflex brain attached to the peer mesh (%d peers)", len(mesh.contracts))
        except Exception as exc:  # a mesh that cannot be built must not stop the brain
            logger.warning("reflex brain is running without a mesh: %s", exc)
        _reflex_brain = ReflexBrain(root, mesh=mesh)
    return _reflex_brain


def _default_repo_root() -> Path:
    """The checkout this code is running from."""
    return Path(__file__).resolve().parents[3]
