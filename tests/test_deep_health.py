"""Regression tests for the health report's evidence contract.

A health report only proves the process started and its modules import. The
serialized form must say so explicitly, and must carry the instant the checks
ran, so a reader never mistakes a liveness answer for dependency readiness.
"""

from datetime import datetime

from friday_deep.health import Check, Health, Report, build


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, "observed_at must be timezone aware"
    return parsed


def test_report_serializes_evidence_class_and_observation_time():
    report = build(modules=("json",))
    payload = report.as_dict()

    assert payload["evidence_class"] == "process_liveness"
    assert _parse(payload["observed_at"])


def test_evidence_fields_present_on_a_hand_built_report():
    report = Report(overall=Health.DEGRADED, checks=[Check("x", Health.DEGRADED, "why")])
    payload = report.as_dict()

    assert payload["overall"] == "degraded"
    assert payload["evidence_class"] == "process_liveness"
    assert _parse(payload["observed_at"])


def test_existing_check_payload_is_unchanged():
    report = build(modules=("json",))
    payload = report.as_dict()

    assert payload["checks"]
    for check in payload["checks"]:
        assert set(check) == {"name", "state", "details"}


def test_missing_module_is_reported_as_degraded_not_failed():
    report = build(modules=("a_module_that_does_not_exist",))
    payload = report.as_dict()

    assert payload["overall"] == "degraded"
    assert payload["evidence_class"] == "process_liveness"
    assert _parse(payload["observed_at"])


def test_observation_time_is_stamped_when_the_report_is_built():
    report = build(modules=())

    # Serializing repeatedly must not move the observation instant: it records
    # when the checks ran, not when someone happened to read them.
    assert report.as_dict()["observed_at"] == report.as_dict()["observed_at"]
    assert _parse(report.observed_at) <= datetime.now(_parse(report.observed_at).tzinfo)
