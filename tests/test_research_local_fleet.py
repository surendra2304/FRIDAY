"""Offline regression tests for the local fleet runner's failure report."""

import json
import sys

from research import local_fleet


def test_launch_exception_is_reported_without_crashing_or_being_overwritten(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(local_fleet, "UNIVERSE", tmp_path)
    monkeypatch.setattr(local_fleet, "port_is_free", lambda _port: True)

    def fail_launch(_agent, _log_dir):
        raise RuntimeError("controlled launch failure")

    monkeypatch.setattr(local_fleet, "launch", fail_launch)
    monkeypatch.setattr(sys, "argv", ["local_fleet.py", "--agents", "friday"])

    assert local_fleet.main() == 1

    report = tmp_path / "FRIDAY" / "reports_and_data" / "local_fleet" / "boot_report.json"
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "friday": {"up": False, "detail": "controlled launch failure"}
    }
