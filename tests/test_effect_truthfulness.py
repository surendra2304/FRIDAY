"""A claim about the world must come from the call that touched the world.

Every test here failed before this batch. They are not style tests: each one is
a sentence FRIDAY said to a user that was not true, or a task it reported as
done that it never did.
"""

from __future__ import annotations

import os
import sys

import pytest

from friday.core.effects import (
    EffectOutcome,
    browser_available,
    launch_argv_verified,
    launch_process_verified,
    open_url_verified,
    pytest_command,
)


# --------------------------------------------------------------- launch claims
def test_launch_of_a_missing_program_is_not_a_success():
    """`Popen(shell=True)` succeeds when the *shell* starts.

    So ``launch_application('notepad')`` said "Launched 'notepad.exe'." on a
    machine with no such program - the shell exited 127 into an unread pipe.
    """
    outcome = launch_process_verified("friday-program-that-does-not-exist-xyz")
    assert outcome.ok is False
    assert "did not run" in outcome.detail
    assert outcome.evidence["returncode"] not in (0, None)


def test_launch_of_a_real_long_running_program_succeeds():
    outcome = launch_process_verified(f'"{sys.executable}" -c "import time; time.sleep(3)"', settle_seconds=0.5)
    assert outcome.ok is True
    assert outcome.evidence["running"] is True


def test_launch_of_a_program_that_runs_and_exits_zero_succeeds():
    outcome = launch_process_verified(f'"{sys.executable}" -c "pass"', settle_seconds=1.0)
    assert outcome.ok is True


def test_argv_launch_verifies_a_real_running_program_without_a_shell():
    outcome = launch_argv_verified(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        settle_seconds=0.5,
    )
    assert outcome.ok is True
    assert outcome.evidence["running"] is True
    assert outcome.evidence["argv"][0] == sys.executable


def test_argv_launch_of_a_missing_program_is_not_a_success():
    outcome = launch_argv_verified(["friday-program-that-does-not-exist-xyz"])
    assert outcome.ok is False
    assert "Could not start" in outcome.detail or "did not run" in outcome.detail
    assert outcome.evidence["argv"] == ["friday-program-that-does-not-exist-xyz"]


def test_empty_argv_is_not_a_success():
    assert launch_argv_verified([]).ok is False
    assert launch_argv_verified([""]).ok is False


def test_empty_command_is_not_a_success():
    assert launch_process_verified("").ok is False
    assert launch_process_verified("   ").ok is False


def test_launch_application_tool_reports_honestly_through_the_registry():
    """The end-to-end shape: a tool result, not a helper, must not lie."""
    from friday.tools.builtin.launch_application import LaunchApplicationTool

    tool = LaunchApplicationTool()
    result = tool.execute(application="friday-program-that-does-not-exist-xyz")
    assert result.is_error is True
    assert result.refused is True, "a missing program is a benign negative, not a malfunction"
    assert "Launched" not in result.content

    real = tool.execute(application=sys.executable, arguments="-c pass")
    assert real.is_error is False


# ----------------------------------------------------------------- url claims
def test_open_url_verified_reports_when_no_browser_takes_the_url(monkeypatch):
    monkeypatch.setattr("friday.core.effects.webbrowser.open", lambda url: False)
    outcome = open_url_verified("https://example.com")
    assert outcome.ok is False
    assert "Nothing was opened" in outcome.detail
    assert outcome.evidence["opened"] is False


def test_open_url_verified_reports_success_it_can_evidence(monkeypatch):
    monkeypatch.setattr("friday.core.effects.webbrowser.open", lambda url: True)
    outcome = open_url_verified("https://example.com")
    assert outcome.ok is True
    assert outcome.evidence["url"] == "https://example.com"
    assert outcome.evidence["opened"] is True
    # browser_available() reflects this machine, so it is asserted by type, not value.
    assert isinstance(outcome.evidence["browser_available"], bool)


def test_open_url_verified_survives_a_raising_browser_layer(monkeypatch):
    def boom(_url):
        raise RuntimeError("no display")

    monkeypatch.setattr("friday.core.effects.webbrowser.open", boom)
    outcome = open_url_verified("https://example.com")
    assert outcome.ok is False
    assert "no display" in outcome.detail


def test_open_whatsapp_does_not_claim_a_browser_it_did_not_get(monkeypatch):
    """`webbrowser.open`'s boolean used to be discarded here."""
    from friday.core.effects import EffectOutcome as _Outcome
    from friday.tools.builtin import whatsapp_tools

    monkeypatch.setattr(
        whatsapp_tools,
        "open_url_verified",
        lambda url: _Outcome(False, "no browser is installed on this machine", {"url": url}),
    )
    result = whatsapp_tools.OpenWhatsAppTool().execute(device="windows")
    assert result.is_error is True
    assert result.refused is True
    assert "Opened" not in result.content


def test_send_whatsapp_web_fallback_does_not_claim_prefill_without_a_browser(monkeypatch):
    from friday.core.effects import EffectOutcome as _Outcome
    from friday.tools.builtin import whatsapp_tools

    monkeypatch.setattr(
        whatsapp_tools,
        "open_url_verified",
        lambda url: _Outcome(False, "no browser is installed on this machine", {"url": url}),
    )
    result = whatsapp_tools.SendWhatsAppMessageTool().execute(recipient="Rahul", message="hi", channel="web")
    assert result.is_error is True
    assert "NOT sent" in result.content
    assert "pre-filled message" not in result.content


def test_browser_available_answers_a_boolean():
    assert isinstance(browser_available(), bool)


# ------------------------------------------------------------------ the tests
def test_pytest_command_uses_fridays_own_interpreter():
    """A bare "pytest" is not on PATH in a venv that was not activated."""
    cmd = pytest_command("-q")
    assert cmd[:3] == [sys.executable, "-m", "pytest"]
    assert cmd[3:] == ["-q"]


def test_run_tests_tool_can_actually_run_a_test():
    from friday.tools.builtin.dev_tools import RunTestsTool

    here = os.path.dirname(os.path.abspath(__file__))
    result = RunTestsTool().execute(test_path=os.path.join(here, "test_fast_path_scope.py"))
    assert "No such file or directory: 'pytest'" not in result.content
    assert result.is_error is False, result.content[:400]


# ---------------------------------------------------- failures that blamed users
def test_weather_does_not_blame_the_spelling_when_the_service_is_unreachable():
    """A user in Bhimavaram was told to verify a correct spelling."""
    from friday.tools.builtin.weather import WeatherTool

    import friday.tools.builtin.weather as weather_module

    original = weather_module.geocode_city_detailed

    def unreachable(_city):
        return None, "lookup_unavailable: the location service could not be reached (ConnectError)"

    weather_module.geocode_city_detailed = unreachable
    try:
        result = WeatherTool().execute(city="Bhimavaram")
    finally:
        weather_module.geocode_city_detailed = original

    assert result.is_error is True
    assert "verify spelling" not in result.content.lower()
    assert "unreachable" in result.content
    assert result.metadata["reason"].startswith("lookup_unavailable")


def test_weather_still_reports_a_genuinely_unknown_place():
    from friday.tools.builtin.weather import WeatherTool

    import friday.tools.builtin.weather as weather_module

    original = weather_module.geocode_city_detailed

    def unknown(_city):
        return None, "unknown_place: the location service does not know that place name"

    weather_module.geocode_city_detailed = unknown
    try:
        result = WeatherTool().execute(city="Notarealplace")
    finally:
        weather_module.geocode_city_detailed = original

    assert result.is_error is True
    assert "spelling" in result.content.lower()


def test_a_valid_android_key_is_not_reported_as_an_unsupported_key():
    """'home' is in KEY_EVENT_MAP; the old failure message listed the key map."""
    import friday.tools.builtin.android_control as android_control

    class NoDevice:
        def is_connected(self):
            return False

        def press_key(self, _key):
            raise AssertionError("press_key must not be reached without a device")

    original = android_control._controller
    android_control._controller = NoDevice()
    try:
        result = android_control.AndroidKeyEventTool().execute(key="home")
        unknown = android_control.AndroidKeyEventTool().execute(key="definitelynotakey")
    finally:
        android_control._controller = original

    assert "no Android device is connected" in result.content
    assert "Supported" not in result.content
    assert "Supported" in unknown.content


# ------------------------------------------------- refusals and the tool breaker
def test_registry_refusals_are_tagged_and_do_not_open_the_circuit_breaker():
    """Three refused calls used to disable the tool for a minute."""
    from friday.tools.registry import ToolRegistry
    from friday.tools.builtin.email_tools import SendEmailTool

    registry = ToolRegistry()
    registry.register(SendEmailTool())

    result = None
    for i in range(5):
        result = registry.execute(
            "send_email",
            {"to_address": "a@b.com", "subject": "s", "body": "b"},
            tool_call_id=f"refusal-{i}",
        )

    assert result is not None
    assert result.is_error is True
    assert result.refused is True
    assert getattr(result.error_detail, "code", None) == "SAFETY_BLOCK"
    assert registry._circuit_breaker.is_open("send_email") is False


def test_an_unknown_tool_is_a_refusal_not_a_malfunction():
    from friday.tools.registry import ToolRegistry

    result = ToolRegistry().execute("no_such_tool_at_all", {})
    assert result.is_error is True
    assert result.refused is True
    assert getattr(result.error_detail, "code", None) == "UNKNOWN_TOOL"


def test_invalid_arguments_are_a_refusal():
    from friday.tools.builtin.calculator import CalculatorTool
    from friday.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    result = registry.execute("calculator", {}, tool_call_id="no-args")
    assert result.is_error is True
    assert result.refused is True


@pytest.mark.parametrize("outcome", [EffectOutcome(True, "ok", {}), EffectOutcome(False, "no", {})])
def test_effect_outcome_exposes_its_evidence(outcome):
    assert outcome.as_dict()["ok"] is outcome.ok
    assert outcome.as_dict()["detail"] == outcome.detail


# ------------------------------------------------- system reports name real things
def test_disk_report_names_the_volume_it_measured():
    """A Linux machine announced a C: drive that does not exist."""
    import os
    import re

    from friday.tools.builtin.health_monitor import HealthCheckTool, disk_mount_point

    content = HealthCheckTool().execute().content
    mount = disk_mount_point()
    assert f"Disk ({mount})" in content
    if os.name != "nt":
        assert "Disk (C:)" not in content
    assert re.search(r"Disk \(.+?\): \d", content)


def test_system_status_names_the_volume_it_measured():
    import os

    from friday.tools.builtin.system_control import SystemControlTool

    result = SystemControlTool().execute(action="system_status")
    assert result.is_error is False
    if os.name != "nt":
        assert "Disk (C:)" not in result.content
        assert "Disk (/)" in result.content


# ---------------------------------------------------- a read that read nothing
def test_read_gmail_inbox_is_not_a_success_when_it_read_nothing(monkeypatch):
    """`is_error=False` with no messages is an inbox the model will summarise."""
    import friday.tools.builtin.gmail_tools as gmail_tools
    from friday.core.effects import EffectOutcome

    monkeypatch.delenv("FRIDAY_EMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("FRIDAY_EMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(
        gmail_tools,
        "get_settings",
        lambda: type("S", (), {"email_address": None, "email_app_password": None})(),
    )
    monkeypatch.setattr(
        "friday.core.effects.open_url_verified",
        lambda url: EffectOutcome(True, f"Opened {url} in the default browser.", {"url": url}),
    )

    result = gmail_tools.ReadGmailInboxTool().execute()

    assert result.is_error is True
    assert result.refused is True
    assert "No mail was read" in result.content
    assert result.metadata["read"] is False


def test_read_gmail_inbox_says_so_when_the_browser_also_failed(monkeypatch):
    import friday.tools.builtin.gmail_tools as gmail_tools
    from friday.core.effects import EffectOutcome

    monkeypatch.setattr(
        gmail_tools,
        "get_settings",
        lambda: type("S", (), {"email_address": None, "email_app_password": None})(),
    )
    monkeypatch.setattr(
        "friday.core.effects.open_url_verified",
        lambda url: EffectOutcome(False, "no browser is installed on this machine.", {"url": url}),
    )

    result = gmail_tools.ReadGmailInboxTool().execute()

    assert result.is_error is True
    assert "no browser is installed" in result.content
    assert result.metadata["read"] is False


# ------------------------------------------------- the device layer's own claims
def test_device_open_url_does_not_claim_a_browser_it_never_reached(monkeypatch):
    """`open_url` returned True unconditionally, including from its `except`."""
    import friday.devices.windows_friday as wf

    monkeypatch.setattr(wf, "browser_available", lambda: False, raising=False)
    monkeypatch.setattr("friday.core.effects.browser_available", lambda: False)
    monkeypatch.setattr("friday.core.effects.open_url_verified",
                        lambda url: EffectOutcome(False, "no browser is installed", {"url": url}))

    controller = wf.WindowsFridayController.__new__(wf.WindowsFridayController)
    assert controller.open_url("https://example.com") is False


def test_device_open_url_reports_a_real_success(monkeypatch):
    import friday.devices.windows_friday as wf

    monkeypatch.setattr("friday.core.effects.browser_available", lambda: True)
    monkeypatch.setattr("friday.core.effects.open_url_verified",
                        lambda url: EffectOutcome(True, "opened", {"url": url}))

    controller = wf.WindowsFridayController.__new__(wf.WindowsFridayController)
    assert controller.open_url("https://example.com") is True


def test_whatsapp_directive_never_claims_a_delivery_receipt():
    """ADB/browser acceptance is not a delivery receipt, and the reply must say so."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "src" / "friday" / "devices" / "windows_friday.py"
    text = source.read_text()
    assert 'f"Delivery verified (Receipt:' not in text
    assert "Delivery is NOT confirmed" in text


def test_android_send_reply_does_not_say_successfully_sent(monkeypatch):
    """A dispatched intent opens the composer; the send is the user's tap."""
    from friday.devices.android_controller import AndroidDeviceController
    from friday.tools.builtin import whatsapp_tools

    class FakeAndroid:
        def is_connected(self):
            return True

        def run_adb(self, _args):
            return 0, "", ""  # Android accepted the intent

        def press_key(self, _key):
            return True

    monkeypatch.setattr(whatsapp_tools, "AndroidDeviceController", lambda: FakeAndroid())
    monkeypatch.setattr(whatsapp_tools.time, "sleep", lambda _s: None)

    result = whatsapp_tools.SendWhatsAppMessageTool().execute(
        recipient="Rahul", message="hi", channel="android"
    )

    assert result.is_error is False
    assert "Successfully sent" not in result.content
    assert "not a delivery receipt" in result.content
    assert result.metadata["delivery_confirmed"] is False


# ------------------------------------------------------- invented dashboard data
def test_the_master_dashboard_feed_is_derived_not_invented():
    """The feed was five literals including a fake P&L and a fake prediction."""
    from friday.ecosystem.command_center import EcosystemCommandCenter
    from friday.ecosystem.master_dashboard import EcosystemMasterDashboard
    from friday.skills.forge_manager import ForgeManagerSkill

    dashboard = EcosystemMasterDashboard(
        command_center=EcosystemCommandCenter(),
        forge_manager=ForgeManagerSkill(),
    )
    rendered = dashboard.render_dashboard()

    for invented in ("76% Bullish", "94.5%", "zero safety breaches", "L2 Order Book Aggregator"):
        assert invented not in rendered, f"invented dashboard content came back: {invented!r}"
    # With nothing reported, the dashboard must say so rather than print a status.
    assert "unknown" in rendered.lower()
    assert "source: " in rendered


def test_a_forge_artifact_path_is_a_claim_not_an_observation():
    """Seeded artifact paths existed nowhere on disk but were printed as delivered."""
    from friday.skills.forge_manager import ForgeManagerSkill

    seeded = ForgeManagerSkill(demo_data=True)
    artifacts = seeded.get_artifacts("forge_task_01")

    assert artifacts["sample_data"] is True
    assert artifacts["artifacts"], "the sample task does claim artifacts"
    assert all(found is False for found in artifacts["artifacts_on_disk"].values()), (
        "no file backs those paths on this machine, so each must report as unfound"
    )
    assert artifacts["delivery_package_on_disk"] is False

    review = seeded.review_task_output("forge_task_01")
    assert "NOT FOUND on disk" in review
    assert "SAMPLE DATA" in review


def test_a_forge_review_does_not_default_a_missing_verification_to_passed():
    """`ver.get('html5_validator', 'PASSED')` reported an absent result as a pass."""
    from friday.skills.forge_manager import ForgeManagerSkill

    forge = ForgeManagerSkill(demo_data=False)
    from friday.skills.forge_manager import ForgeTaskDetails

    forge._tasks["forge_task_99"] = ForgeTaskDetails(
        task_id="forge_task_99",
        goal="Build something that was never verified",
        expanded_specification="",
        priority="NORMAL",
        state="COMPLETED",
        progress_pct=100.0,
        files_created=[],
        artifacts=[],
        verification_results={},
        test_coverage_pct=0.0,
        logs=[],
        delivery_package_path=None,
    )
    review = forge.review_task_output("forge_task_99")

    assert "PASSED" not in review, "no verification ran, so nothing may be reported as passed"
    assert "no verification result was recorded" in review
    assert "none recorded" in review
