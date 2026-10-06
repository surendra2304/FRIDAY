"""Tests for the standing autonomy mandate (cognition.mandate).

The mandate is what lets FRIDAY repair itself unattended without an agent ever
approving its own work. These tests hold that line: they prove the owner's
pre-recorded authority is *verified*, bounded and revocable, and that it cannot
be forged, reused after expiry, widened beyond its scope, or issued by an agent.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from friday.cognition.mandate import (
    ALL_SCOPES,
    MANDATE_KEY_ENV,
    SCOPE_CONFIG_REPAIR,
    SCOPE_DEPENDENCY_INSTALL,
    SCOPE_PEER_RECONNECT,
    SCOPE_SOURCE_REPAIR,
    AutonomyMandate,
    MandateAuthority,
    MandateLedger,
    verify_mandate,
)

KEY = b"owner-autonomy-signing-key-for-tests"


@pytest.fixture
def authority(tmp_path: Path) -> MandateAuthority:
    return MandateAuthority(
        key=KEY,
        ledger=MandateLedger(str(tmp_path / "mandates.json")),
        allow_auto_issue=False,
    )


class TestIssuing:
    """Only the owner may grant autonomy, and only within a known vocabulary."""

    def test_owner_can_issue_and_it_is_verifiable(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", ttl_seconds=600)
        assert verify_mandate(document, KEY) is True
        assert document["issued_by"] == "surendra"
        assert document["mandate_id"].startswith("mandate_")

    @pytest.mark.parametrize(
        "impostor",
        ["friday", "forge", "sentinel", "memora", "  ", "bot", "system", "automation"],
    )
    def test_an_agent_cannot_issue_a_mandate(self, authority: MandateAuthority, impostor: str) -> None:
        with pytest.raises(ValueError, match="agent, not the owner"):
            authority.issue(impostor, ttl_seconds=600)

    def test_unknown_scope_is_refused_rather_than_ignored(self, authority: MandateAuthority) -> None:
        with pytest.raises(ValueError, match="unknown scope"):
            authority.issue("surendra", scopes=("source_repair", "take_over_the_world"))

    def test_non_positive_lifetime_is_refused(self, authority: MandateAuthority) -> None:
        with pytest.raises(ValueError, match="positive lifetime"):
            authority.issue("surendra", ttl_seconds=0)

    def test_issuing_without_a_key_is_refused(self, tmp_path: Path) -> None:
        authority = MandateAuthority(key=None, ledger=MandateLedger(str(tmp_path / "m.json")))
        authority._key = None
        with pytest.raises(RuntimeError, match=MANDATE_KEY_ENV):
            authority.issue("surendra")


class TestSignatureIntegrity:
    """A mandate is a signed document, so nothing about it can be edited."""

    def test_flipping_a_scope_invalidates_the_signature(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        document["scopes"] = [SCOPE_SOURCE_REPAIR, SCOPE_DEPENDENCY_INSTALL]
        assert verify_mandate(document, KEY) is False

    def test_extending_the_expiry_invalidates_the_signature(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", ttl_seconds=600)
        document["expires_at"] = document["expires_at"] + 86400
        assert verify_mandate(document, KEY) is False

    def test_widening_allowed_paths_invalidates_the_signature(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", allowed_paths=("src/**",), ttl_seconds=600)
        document["allowed_paths"] = ["**"]
        assert verify_mandate(document, KEY) is False

    def test_a_signature_from_another_key_is_refused(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", ttl_seconds=600)
        assert verify_mandate(document, b"a-different-key") is False

    def test_a_mandate_with_no_signature_is_refused(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", ttl_seconds=600)
        document.pop("signature")
        assert verify_mandate(document, KEY) is False


class TestEvaluation:
    """The verdict decides whether an unattended change may proceed."""

    def test_no_key_means_no_autonomy(self, tmp_path: Path) -> None:
        authority = MandateAuthority(key=None, ledger=MandateLedger(str(tmp_path / "m.json")))
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/friday/x.py",))
        assert verdict.allowed is False
        assert verdict.refusal == "NO_KEY"

    def test_no_mandate_means_no_autonomy(self, authority: MandateAuthority) -> None:
        """Denied, and labelled for what is actually missing.

        This assertion used to read `NO_KEY`, and the key *is* configured in this
        fixture: the label sent the owner to check a key that was already there,
        while the CLI's "grant standing autonomy" hint keyed off a refusal name
        that did not exist in the vocabulary at all.
        """
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/friday/x.py",))
        assert verdict.allowed is False
        assert verdict.refusal == "NO_MANDATE"
        assert "ever been granted" in verdict.reason

    def test_an_expired_mandate_is_labelled_expired_not_missing(self, authority: MandateAuthority) -> None:
        """A grant that ran out and a machine never granted are different problems."""
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        document["expires_at"] = 1.0   # long past; the ledger stores what it is given
        authority._ledger.record_grant(document)
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/friday/x.py",))
        assert verdict.allowed is False
        assert verdict.refusal == "EXPIRED"
        assert "expired or been revoked" in verdict.reason

    def test_a_revoked_mandate_is_labelled_revoked(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        authority.revoke(document["mandate_id"], "the owner withdrew it")
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/friday/x.py",))
        assert verdict.allowed is False
        assert verdict.refusal in {"EXPIRED", "REVOKED"}

    def test_an_active_mandate_permits_a_granted_scope(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/friday/agent/agent.py",))
        assert verdict.allowed is True
        assert verdict.mandate_id

    def test_an_ungranted_scope_is_refused_by_name(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        verdict = authority.evaluate(SCOPE_DEPENDENCY_INSTALL)
        assert verdict.allowed is False
        assert verdict.refusal == "SCOPE_NOT_GRANTED"
        assert SCOPE_SOURCE_REPAIR in verdict.reason

    def test_a_file_outside_the_mandate_is_refused(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("src/**",), ttl_seconds=600)
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=(".github/workflows/ci.yml",))
        assert verdict.allowed is False
        assert verdict.refusal == "FILE_NOT_PERMITTED"

    def test_too_many_files_is_refused(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), max_files_per_change=1, ttl_seconds=600)
        verdict = authority.evaluate(
            SCOPE_SOURCE_REPAIR, paths=("src/a.py", "src/b.py")
        )
        assert verdict.allowed is False
        assert verdict.refusal == "TOO_MANY_FILES"

    def test_missing_test_evidence_is_refused_when_the_mandate_demands_it(
        self, authority: MandateAuthority
    ) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), ttl_seconds=600)
        verdict = authority.evaluate(
            SCOPE_SOURCE_REPAIR, paths=("src/a.py",), has_test_evidence=False
        )
        assert verdict.allowed is False
        assert verdict.refusal == "NO_TEST_EVIDENCE"

    def test_windows_and_posix_paths_agree(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), allowed_paths=("src/**",), ttl_seconds=600)
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=(".\\src\\friday\\x.py",))
        assert verdict.allowed is True


class TestExpiryAndRevocation:
    """A mandate is bounded in time and can be withdrawn."""

    def test_an_expired_mandate_permits_nothing(self, tmp_path: Path) -> None:
        ledger = MandateLedger(str(tmp_path / "m.json"))
        authority = MandateAuthority(key=KEY, ledger=ledger)
        mandate = AutonomyMandate(issued_by="surendra", issued_at=time.time() - 7200, expires_at=time.time() - 60)
        ledger.record_grant(mandate.sign(KEY))
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",))
        assert verdict.allowed is False

    def test_a_revoked_mandate_permits_nothing(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", ttl_seconds=600)
        assert authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is True

        assert authority.revoke(document["mandate_id"], "owner withdrew it") is True
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",))
        assert verdict.allowed is False

    def test_revocation_of_an_unknown_mandate_reports_false(self, authority: MandateAuthority) -> None:
        assert authority.revoke("mandate_does_not_exist") is False

    def test_a_budgeted_mandate_stops_after_its_budget(self, authority: MandateAuthority) -> None:
        document = authority.issue("surendra", scopes=(SCOPE_SOURCE_REPAIR,), max_changes=2, ttl_seconds=600)
        assert authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is True
        authority.record_use(document["mandate_id"])
        authority.record_use(document["mandate_id"])
        verdict = authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",))
        assert verdict.allowed is False
        assert "budget" in verdict.reason


class TestDurability:
    """Authority survives a restart, and a corrupt ledger fails closed."""

    def test_a_grant_survives_a_restart(self, tmp_path: Path) -> None:
        path = str(tmp_path / "m.json")
        first = MandateAuthority(key=KEY, ledger=MandateLedger(path))
        document = first.issue("surendra", ttl_seconds=600)

        second = MandateAuthority(key=KEY, ledger=MandateLedger(path))
        assert second.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is True
        assert second.active()[0].mandate_id == document["mandate_id"]

    def test_a_revocation_survives_a_restart(self, tmp_path: Path) -> None:
        path = str(tmp_path / "m.json")
        first = MandateAuthority(key=KEY, ledger=MandateLedger(path))
        document = first.issue("surendra", ttl_seconds=600)
        first.revoke(document["mandate_id"], "not needed")

        second = MandateAuthority(key=KEY, ledger=MandateLedger(path))
        assert second.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is False

    def test_a_corrupt_ledger_grants_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text("{not json at all", encoding="utf-8")
        authority = MandateAuthority(key=KEY, ledger=MandateLedger(str(path)))
        assert authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is False
        assert authority.active() == []

    def test_a_ledger_from_another_version_is_not_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text('{"version": 99, "granted": {"x": {}}}', encoding="utf-8")
        ledger = MandateLedger(str(path))
        assert ledger.granted_raw() == []


class TestAutoIssue:
    """Zero-ceremony autonomy, only when the operator asks for it."""

    def test_auto_issue_is_off_by_default(self, authority: MandateAuthority) -> None:
        assert authority.ensure_mandate("surendra") is None

    def test_auto_issue_grants_when_enabled(self, tmp_path: Path) -> None:
        authority = MandateAuthority(
            key=KEY,
            ledger=MandateLedger(str(tmp_path / "m.json")),
            allow_auto_issue=True,
        )
        document = authority.ensure_mandate("surendra", ttl_seconds=600)
        assert document is not None
        assert authority.evaluate(SCOPE_SOURCE_REPAIR, paths=("src/a.py",)).allowed is True

    def test_ensure_mandate_reuses_an_existing_grant(self, authority: MandateAuthority) -> None:
        existing = authority.issue("surendra", ttl_seconds=600)
        reused = authority.ensure_mandate("surendra", ttl_seconds=600)
        assert reused is not None
        assert reused["mandate_id"] == existing["mandate_id"]


class TestStatusReporting:
    """The operator can always see why autonomy is or is not in force."""

    def test_status_names_the_missing_key(self, tmp_path: Path) -> None:
        authority = MandateAuthority(key=None, ledger=MandateLedger(str(tmp_path / "m.json")))
        status = authority.status()
        assert status["status"] == "NO_KEY"
        assert MANDATE_KEY_ENV in status["missing"]

    def test_status_says_awaiting_mandate_when_none_is_granted(self, authority: MandateAuthority) -> None:
        status = authority.status()
        assert status["status"] == "AWAITING_MANDATE"
        assert status["grant_command"] == "friday --grant-autonomy"

    def test_status_reports_active_mandates(self, authority: MandateAuthority) -> None:
        authority.issue("surendra", ttl_seconds=600, note="evening maintenance")
        status = authority.status()
        assert status["status"] == "ACTIVE"
        assert status["active_mandates"][0]["note"] == "evening maintenance"

    def test_all_scopes_are_disjointly_named(self) -> None:
        assert len(ALL_SCOPES) == len(set(ALL_SCOPES))
        assert SCOPE_PEER_RECONNECT in ALL_SCOPES
        assert SCOPE_CONFIG_REPAIR in ALL_SCOPES
