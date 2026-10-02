"""The Gmail send path must never claim a send it did not confirm.

These are adversarial conditions taken from a real desktop session, not invented
edge cases. The failure they all share: ``open_gmail`` used to open a Gmail draft,
fire Ctrl+Enter from a background thread that swallowed every exception, and
immediately return ``open_url()``'s result - so "a browser tab opened" was
reported to the user as "message dispatched", with a receipt stamped SENT before
anything had been sent.

What is asserted here is a truthfulness contract, so the browser, the SMTP server
and the Win32 input driver are all replaced at their module boundary. The
production logic under test - the branching, the receipt, the wording - is real.
"""

import threading
from types import SimpleNamespace

import pytest

from friday.core import config as friday_config
from friday.devices import windows_friday as wf
from friday.devices.windows_friday import windows_friday

# Nothing here needs a Windows host. The desktop attachment is the only step the
# product performs that cannot be substituted, and it is guarded by platform in
# open_gmail itself. The input driver, the window lookup and the foreground call
# are all replaced below, so the contract under test - what a receipt is allowed
# to claim - is asserted identically on every runner.


@pytest.fixture(autouse=True)
def no_smtp_credentials(monkeypatch):
    """No SMTP credentials unless a test supplies them."""
    monkeypatch.delenv("FRIDAY_EMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("FRIDAY_EMAIL_APP_PASSWORD", raising=False)
    # open_gmail imports get_settings inside the function body, so the patch has to
    # land on the defining module rather than on the one that calls it.
    monkeypatch.setattr(
        friday_config, "get_settings",
        lambda: SimpleNamespace(email_address=None, email_app_password=None),
        raising=False,
    )
    monkeypatch.setattr(
        wf, "_GMAIL_AUTOSEND_RETRY_DELAYS", (0.0, 0.0), raising=False
    )
    monkeypatch.setattr(
        wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 3.0, raising=False
    )


class _InputDriver:
    """Stand-in for the Win32 driver that records the keystroke it was told to send."""

    def __init__(self, result: bool = True, raises: Exception | None = None, log: list | None = None):
        self.result = result
        self.raises = raises
        self.log = log if log is not None else []

    def hotkey(self, keys):
        if self.raises is not None:
            raise self.raises
        self.log.append(("hotkey", tuple(keys)))
        return self.result


def _install(
    monkeypatch,
    *,
    driver=None,
    hwnd: int | None = 1234,
    smtp=None,
    smtp_raises: Exception | None = None,
    opened: bool = True,
):
    """Wire up one concrete desktop condition."""
    monkeypatch.setattr(windows_friday, "open_url", lambda url: opened, raising=False)
    monkeypatch.setattr(
        windows_friday, "_get_active_browser_hwnd", lambda keywords=None: hwnd, raising=False
    )
    import friday.devices.app_launcher as launcher

    monkeypatch.setattr(launcher, "force_window_foreground", lambda h: True, raising=False)
    import friday.vision.windows_input_driver as wdrv

    monkeypatch.setattr(wdrv, "WindowsNativeInputDriver", lambda: driver or _InputDriver(), raising=False)

    if smtp is not None or smtp_raises is not None:
        import friday.tools.builtin.email_tools as et

        def _send(**kwargs):
            if smtp_raises is not None:
                raise smtp_raises
            return smtp

        monkeypatch.setattr(et, "_send_smtp_email", _send, raising=False)
        monkeypatch.setattr(
            friday_config, "get_settings",
            lambda: SimpleNamespace(email_address="me@real.com", email_app_password="secret"),
            raising=False,
        )


# --------------------------------------------------------------------------
# The regression that produced the real bug report.
# --------------------------------------------------------------------------


def test_the_return_waits_for_the_keystroke_rather_than_racing_ahead_of_it(monkeypatch):
    """Fire-and-forget was the bug: the caller reported before the send was even attempted."""
    events: list[str] = []
    driver = _InputDriver(log=events)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_RETRY_DELAYS", (0.4, 0.4), raising=False)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 5.0, raising=False)
    _install(monkeypatch, driver=driver)

    ok, _ = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="the meeting moved to 3 PM.")
    events.append("returned")

    assert ("hotkey", ("ctrl", "enter")) in events, "the send keystroke was never attempted"
    assert events.index(("hotkey", ("ctrl", "enter"))) < events.index("returned"), (
        "open_gmail returned before its keystroke was dispatched - the caller is "
        "being told about a send that had not happened yet"
    )
    assert ok is False


# --------------------------------------------------------------------------
# Every condition below must yield "not sent", never a success.
# --------------------------------------------------------------------------


def test_a_draft_that_was_opened_is_never_reported_as_sent(monkeypatch):
    """The keystroke went through and Gmail still cannot be observed from here."""
    _install(monkeypatch, driver=_InputDriver(result=True))
    ok, msg = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="the meeting moved to 3 PM.")
    assert ok is False
    assert "NOT sent" in msg
    assert "Sent folder" in msg, "the user must be told where to check for the truth"


def test_an_input_driver_blocked_by_app_control_is_not_reported_as_sent(monkeypatch):
    """Real condition on this machine: the native input DLL is blocked by policy."""
    _install(monkeypatch, driver=_InputDriver(raises=OSError("dll load failed")))
    ok, msg = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False
    assert "dll load failed" in msg, "the actual cause must reach the user, not just a generic failure"


def test_a_keystroke_the_driver_refuses_is_not_reported_as_sent(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=False))
    ok, _ = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False


def test_no_gmail_window_on_screen_is_not_reported_as_sent(monkeypatch):
    """The browser never came to the foreground, so nothing was pressed at all."""
    _install(monkeypatch, driver=_InputDriver(result=True), hwnd=None)
    ok, msg = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False
    assert "could not press send" in msg


def test_a_browser_that_refuses_to_open_is_not_reported_as_sent(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=True), opened=False)
    ok, _ = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False


def test_a_wedged_send_thread_does_not_hang_the_agent_forever(monkeypatch):
    """A driver that never returns must not pin the caller past the bound."""
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_RETRY_DELAYS", (30.0, 30.0), raising=False)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 0.5, raising=False)

    class _Wedged:
        def hotkey(self, keys):
            threading.Event().wait(60)
            return True

    _install(monkeypatch, driver=_Wedged())
    finished = threading.Event()
    result: list = []

    def _call():
        result.append(windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body"))
        finished.set()

    threading.Thread(target=_call, daemon=True).start()
    assert finished.wait(timeout=8), "open_gmail blocked past its bound on a wedged send thread"
    assert result[0][0] is False


# --------------------------------------------------------------------------
# The SMTP path is the only one allowed to report a send.
# --------------------------------------------------------------------------


def test_a_confirmed_smtp_send_is_the_only_thing_that_reports_sent(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=True), smtp=(True, "250 OK"))
    ok, msg = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is True
    assert "sent successfully" in msg


def test_an_smtp_failure_falls_through_without_claiming_a_send(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=True), smtp=(False, "535 auth failed"))
    ok, _ = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False


def test_an_smtp_layer_that_explodes_does_not_claim_a_send(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=True), smtp_raises=RuntimeError("no network"))
    ok, _ = windows_friday.open_gmail(to="alice@example.com", subject="Meeting Update", body="body")
    assert ok is False


# --------------------------------------------------------------------------
# End to end, through the exact directive from the real report.
# --------------------------------------------------------------------------


def test_end_to_end_the_real_directive_never_produces_a_sent_receipt(monkeypatch):
    """The whole chain that produced the stuck draft, asserted end to end."""
    _install(monkeypatch, driver=_InputDriver(result=False))
    monkeypatch.setattr(windows_friday, "_lookup_contact_email", lambda name: None, raising=False)

    handled, reply, meta = windows_friday.handle_directive(
        "send an email to alice saying the meeting moved to 3 PM"
    )
    assert handled is True

    receipt = meta["receipt"]
    assert receipt["status"] != "SENT", (
        "a receipt was stamped SENT for a message that was never confirmed as sent"
    )
    assert receipt["status"] == "NOT_CONFIRMED"
    assert receipt["provider"] == "gmail_web", "the receipt named an SMTP provider it never used"
    assert meta["success"] is False

    assert "NOT SENT" in reply
    for lie in ("dispatched", "Message sent", "has been sent"):
        assert lie not in reply, f"the reply still claims a send: {lie!r}"


def test_end_to_end_a_confirmed_smtp_send_does_produce_a_sent_receipt(monkeypatch):
    _install(monkeypatch, driver=_InputDriver(result=False), smtp=(True, "250 OK"))
    monkeypatch.setattr(windows_friday, "_lookup_contact_email", lambda name: None, raising=False)

    handled, reply, meta = windows_friday.handle_directive(
        "send an email to alice saying the meeting moved to 3 PM"
    )
    assert handled is True
    assert meta["success"] is True
    assert meta["receipt"]["status"] == "SENT"
    assert meta["receipt"]["provider"] == "smtp.gmail.com"
    assert "sent and confirmed" in reply