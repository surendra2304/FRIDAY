"""The Phase F1 grading rule, pinned.

The whole value of the fleet report is that it refuses to grade itself
generously. A service that answers 200 but does not label its own claim is
running old code, and calling that "live" is precisely the error that already
cost this project two owner-blocked redeploys. So the rule is pinned here, where
a future change to it has to be deliberate.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "fleet_truth.py"
_spec = importlib.util.spec_from_file_location("fleet_truth", MODULE_PATH)
assert _spec and _spec.loader
fleet_truth = importlib.util.module_from_spec(_spec)
# dataclasses resolve their own module through sys.modules while the class body
# executes, so the module has to be registered before it runs.
sys.modules["fleet_truth"] = fleet_truth
_spec.loader.exec_module(fleet_truth)

Probe = fleet_truth.Probe


def _probe(**kwargs) -> Probe:
    base = {"service": "x", "url": "http://x"}
    return Probe(**{**base, **kwargs})


def test_a_service_that_answers_with_evidence_fields_is_live():
    probe = _probe(
        reachable=True,
        status_code=200,
        evidence_class="process_liveness",
        observed_at="2026-10-02T00:00:00+00:00",
    )
    assert probe.verdict == "LIVE"


def test_an_old_build_that_answers_without_evidence_is_stale_not_live():
    """The failure this whole phase exists to make visible."""
    probe = _probe(
        reachable=True,
        status_code=200,
        reported_status="UP",
        missing_fields=["evidence_class", "observed_at"],
    )
    assert probe.verdict == "STALE_BUILD"


def test_partial_evidence_is_not_enough():
    probe = _probe(
        reachable=True,
        status_code=200,
        evidence_class="process_liveness",
        observed_at=None,
        missing_fields=["observed_at"],
    )
    assert probe.verdict == "STALE_BUILD"


def test_a_service_that_does_not_answer_is_unreachable_not_stale():
    """A cold start on a free tier must not be graded as an out-of-date build."""
    probe = _probe(reachable=False, status_code=None, error="ConnectError")
    assert probe.verdict == "UNREACHABLE"


def test_stale_and_unreachable_are_never_the_same_verdict():
    """Merging them would hide a redeploy behind an outage, or the reverse."""
    assert _probe(reachable=False).verdict != _probe(
        reachable=True, missing_fields=["evidence_class"]
    ).verdict


def test_the_required_fields_are_the_two_that_make_a_claim_falsifiable():
    assert fleet_truth.REQUIRED_FIELDS == ("evidence_class", "observed_at")


def test_a_closed_port_is_reported_unreachable_for_real():
    """Not mocked: a socket nothing is listening on, so the check cannot lie."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = sock.getsockname()[1]
    probe = fleet_truth.probe_service("dead", f"http://127.0.0.1:{dead_port}", timeout=5.0)
    assert probe.verdict == "UNREACHABLE"
    assert probe.reachable is False


def test_every_blocked_item_names_an_action_and_a_verification():
    """A blocker with no next step is an excuse, not a blocker."""
    assert fleet_truth.OWNER_BLOCKED, "there are known owner-blocked items to name"
    for item in fleet_truth.OWNER_BLOCKED:
        assert item["action"].strip(), f"{item['item']} names no action"
        assert item["verify"].strip(), f"{item['item']} names no verification"
        assert "owner" not in item["action"].lower() or "Render" in item["action"]


def test_every_service_in_the_fleet_is_probed():
    assert len(fleet_truth.FLEET) == 9
    assert len({name for name, _, _ in fleet_truth.FLEET}) == 9


@pytest.mark.parametrize("entry", fleet_truth.FLEET)
def test_no_service_is_probed_without_a_https_url(entry):
    """An http:// probe would let the verdict be trivially forged in transit."""
    _, url, _ = entry
    assert url.startswith("https://")
