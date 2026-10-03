"""What a Gmail send is allowed to claim.

``open_gmail`` used to open a draft, fire Ctrl+Enter from a daemon thread that
swallowed every exception, and return the result of opening a browser tab - so
a draft on screen was reported as a sent message, with a receipt stamped SENT
before anything was attempted.

The browser, SMTP and the Win32 driver are replaced at their module boundary.
The logic under test - the branching, the receipt, the wording - is real, and
the platform guard for the one step that cannot be substituted lives in the
product, so every case runs on every runner.
"""

import smtplib
import threading
import time
from types import SimpleNamespace

import pytest

from friday.core import config as friday_config
from friday.devices import windows_friday as wf
from friday.devices.windows_friday import GmailSend, windows_friday
from friday.tools.builtin.email_tools import SendOutcome

ALICE = "FRIDAY, email Alice that the meeting moved to 3 PM."
ALICE_ADDRESSED = "FRIDAY, email alice@realwork.com that the meeting moved to 3 PM"


class _Driver:
    """Stand-in for the Win32 driver. Records the keystroke it was told to send."""

    def __init__(self, ok: bool = True, raises: Exception | None = None, log: list | None = None):
        self.ok, self.raises, self.log = ok, raises, [] if log is None else log

    def hotkey(self, keys):
        if self.raises is not None:
            raise self.raises
        self.log.append(("hotkey", tuple(keys)))
        return self.ok


def _install(monkeypatch, *, driver=None, hwnd=1234, title="Compose Mail - u@gmail.com - Gmail",
             smtp=None, opens=True):
    """Wire up one desktop condition. ``smtp`` is a result tuple or an exception."""
    monkeypatch.setattr(windows_friday, "open_url", lambda url: opens)
    monkeypatch.setattr(windows_friday, "_get_active_browser_hwnd", lambda keywords=None: hwnd)
    monkeypatch.setattr(windows_friday, "_is_gmail_window", lambda h: "gmail" in title.lower())

    import friday.devices.app_launcher as launcher
    import friday.vision.windows_input_driver as wdrv

    monkeypatch.setattr(launcher, "force_window_foreground", lambda h: True)
    monkeypatch.setattr(wdrv, "WindowsNativeInputDriver", lambda: driver or _Driver())

    if smtp is not None:
        import friday.tools.builtin.email_tools as et

        def _send(**kwargs):
            if isinstance(smtp, Exception):
                raise smtp
            return smtp if hasattr(smtp, "sent") else SendOutcome(*smtp)

        monkeypatch.setattr(et, "_send_smtp_email", _send)
        # open_gmail imports get_settings inside its body, so the patch has to
        # land on the defining module, not the one that calls it.
        monkeypatch.setattr(
            friday_config, "get_settings",
            lambda: SimpleNamespace(email_address="me@real.com", email_app_password="secret"),
        )


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """No SMTP unless a test supplies it, and no real waiting."""
    monkeypatch.delenv("FRIDAY_EMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("FRIDAY_EMAIL_APP_PASSWORD", raising=False)
    monkeypatch.setattr(
        friday_config, "get_settings",
        lambda: SimpleNamespace(email_address=None, email_app_password=None),
    )
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_POLL_SECONDS", 0.01)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 3.0)


# --------------------------------------------------------------------------
# Acting on the window.
# --------------------------------------------------------------------------


def test_the_return_waits_for_the_keystroke_rather_than_racing_ahead_of_it(monkeypatch):
    """Fire-and-forget was the bug: the caller reported before the send was attempted."""
    log: list = []
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_SETTLE_SECONDS", 0.4)
    _install(monkeypatch, driver=_Driver(log=log))

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok = outcome.sent
    log.append("returned")

    assert ("hotkey", ("ctrl", "enter")) in log, "the send keystroke was never attempted"
    assert log.index(("hotkey", ("ctrl", "enter"))) < log.index("returned"), (
        "open_gmail returned before its keystroke was dispatched"
    )
    assert ok is False


def test_the_keystroke_never_lands_in_a_non_gmail_window(monkeypatch):
    """The browser search falls back to any Chrome window.

    Measured: with no Gmail open it returned a window titled CodeTantra-SEA, so
    the keystroke went to an unrelated app while the caller believed otherwise.
    """
    log: list = []
    _install(monkeypatch, driver=_Driver(log=log), title="CodeTantra-SEA")

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert not log, "a keystroke was sent into a window that is not Gmail"
    assert "could not press send" in msg
    assert ok is False


def test_a_gmail_window_is_still_acted_on(monkeypatch):
    """The window check must not stop the send when Gmail really is the window."""
    log: list = []
    _install(monkeypatch, driver=_Driver(log=log))

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert ("hotkey", ("ctrl", "enter")) in log
    assert "pressed Ctrl+Enter" in msg
    assert ok is False, "acting on a Gmail window still cannot confirm the send"


def test_the_wait_is_a_ceiling_not_a_fixed_cost(monkeypatch):
    """The old code slept 4.5s, looked once, slept 2.5s more, then answered.

    Polling means the caller waits for the answer, not for a timer - but a
    browser that never shows up still gets the whole budget, because "the
    compose window was not there" is a real finding.
    """
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 30.0)
    _install(monkeypatch)

    started = time.monotonic()
    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok = outcome.sent
    assert time.monotonic() - started < 2.0, "waited the full budget for a window already on screen"
    assert ok is False

    _install(monkeypatch, hwnd=None)  # never appears
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 0.5)
    started = time.monotonic()
    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail
    assert 0.4 < time.monotonic() - started < 3.0, "a missing window must still get the full budget"
    assert "could not press send" in msg


def test_a_window_that_appears_late_is_still_caught(monkeypatch):
    """Polling must not give up early on a browser that needs a moment."""
    polls = {"n": 0}
    _install(monkeypatch)

    def _late(keywords=None):
        polls["n"] += 1
        return 4321 if polls["n"] >= 4 else None

    monkeypatch.setattr(windows_friday, "_get_active_browser_hwnd", _late)

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert polls["n"] >= 4, "gave up before the browser had a fair chance"
    assert "pressed Ctrl+Enter" in msg
    assert ok is False


@pytest.mark.parametrize("condition", ["no_window", "driver_refuses", "driver_blocked", "no_browser"])
def test_no_failure_condition_is_reported_as_a_send(monkeypatch, condition):
    """Each way the send can fail yields a refusal to claim, never a success."""
    kwargs = {
        "no_window": {"hwnd": None},
        "driver_refuses": {"driver": _Driver(ok=False)},
        "driver_blocked": {"driver": _Driver(raises=OSError("dll load failed"))},
        "no_browser": {"opens": False},
    }[condition]
    _install(monkeypatch, **kwargs)

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert ok is False
    assert "NOT sent" in msg or "NOT SENT" in msg


def test_a_failure_reason_reaches_the_user_rather_than_only_the_log(monkeypatch):
    """The blocked driver is a real condition on this machine; say why."""
    _install(monkeypatch, driver=_Driver(raises=OSError("dll load failed")))

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert "dll load failed" in msg, "the actual cause must reach the user"
    assert ok is False


def test_a_wedged_send_thread_does_not_hang_the_agent_forever(monkeypatch):
    """A driver that never returns must not pin the caller past the bound."""

    class _Wedged:
        def hotkey(self, keys):
            threading.Event().wait(60)
            return True

    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_POLL_SECONDS", 30.0)
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 0.5)
    _install(monkeypatch, driver=_Wedged())

    done = threading.Event()
    result: list = []
    threading.Thread(
        target=lambda: (result.append(windows_friday.open_gmail(to="a@b.com", subject="S", body="b")), done.set()),
        daemon=True,
    ).start()

    assert done.wait(timeout=8), "open_gmail blocked past its bound on a wedged send thread"
    assert result[0][0] is False


# --------------------------------------------------------------------------
# The receipt may only say SENT when a send was confirmed.
# --------------------------------------------------------------------------


def test_a_confirmed_smtp_send_is_the_only_thing_that_reports_sent(monkeypatch):
    _install(monkeypatch, smtp=(True, "250 OK"))

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok, msg = outcome.sent, outcome.detail

    assert ok is True
    assert "sent successfully" in msg


@pytest.mark.parametrize("smtp", [(False, "535 auth failed"), RuntimeError("no network")])
def test_an_smtp_failure_falls_through_without_claiming_a_send(monkeypatch, smtp):
    _install(monkeypatch, smtp=smtp)

    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    ok = outcome.sent

    assert ok is False


# ---------------------------------------------------------------------------
# What the server refused, not what we hoped it accepted
# ---------------------------------------------------------------------------
# sendmail raises only when EVERY recipient is refused. A partial refusal comes
# back as a dict and no exception at all, so both send paths used to read that
# as success: a recipient the server had answered "550 Mailbox unavailable"
# still produced "Email successfully sent", a SENT receipt and success=True.
#
# These cases replace the transport only. _send_smtp_email really runs, and so
# does everything it does with sendmail's return value - the exact line every
# other stub in this file sits above, which is why 22 cases of receipt
# truthfulness never reached it.


def _server_that_refuses(refused: dict):
    """A real SMTP conversation obeying smtplib's two refusal shapes.

    ``smtplib.SMTP.sendmail`` returns the refusal dict when *some* recipients
    are refused and raises ``SMTPRecipientsRefused`` once *every* one of them
    is. A fake that always returned a dict was showing the product a state no
    SMTP server can produce, which is how four cases came to pass against a
    branch that never runs in production.
    """

    class _Server:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, recipients, message):
            errs = dict(refused)
            if errs and len(errs) == len(recipients):
                raise smtplib.SMTPRecipientsRefused(errs)
            return errs

    return _Server


def _with_credentials(monkeypatch):
    """Every binding site that resolves the sending account, all at once.

    open_gmail imports get_settings inside its body while both send tools bind
    it at their own module level, so patching only the defining module leaves
    the tools reading the real config - and they then quietly take the
    no-credentials branch instead of the branch under test.
    """
    import friday.tools.builtin.email_tools as et
    from friday.tools.builtin import gmail_tools as gt

    def settings():
        return SimpleNamespace(email_address="me@real.com", email_app_password="secret")

    for target in (friday_config, et, gt):
        monkeypatch.setattr(target, "get_settings", settings)


def test_a_refused_recipient_is_never_reported_as_sent(monkeypatch):
    """The refusal arrived as a return value, so no exception caught it."""
    import friday.tools.builtin.email_tools as et

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )

    outcome = et._send_smtp_email(to_address="bob@bad.invalid", subject="S", body="B")
    ok, message = outcome.sent, outcome.detail

    assert ok is False
    assert "successfully sent" not in message
    assert "bob@bad.invalid" in message, "the refusal has to name who was refused"
    assert "550" in message, "the server's own reason has to survive into the report"
    assert "refused every recipient" in message, (
        "one bad address is a refusal, not a transport error - the stdlib raises "
        "SMTPRecipientsRefused here, so this branch is the ordinary case"
    )
    assert "{'" not in message, "a raw Python dict is not a report to a user"


def test_a_partial_send_names_who_arrived_and_who_did_not(monkeypatch):
    """One accepted and one refused: the case easiest to overstate as sent."""
    import friday.tools.builtin.email_tools as et

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )

    outcome = et._send_smtp_email(
        to_address=["alice@realwork.com", "bob@bad.invalid"], subject="S", body="B")
    ok, message = outcome.sent, outcome.detail

    assert ok is False, "a send that lost a recipient is not a send that succeeded"
    assert "bob@bad.invalid" in message
    assert "alice@realwork.com" in message, (
        "the recipient that did arrive is named, so the user knows what happened"
    )


def test_the_receipt_cannot_carry_a_recipient_the_server_refused(monkeypatch):
    """End to end: the receipt the user is shown must not claim this send."""
    import friday.tools.builtin.email_tools as et

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )
    # Isolate the SMTP verdict: the web fallback must not be mistaken for it.
    monkeypatch.setattr(windows_friday, "open_url", lambda url: True)
    monkeypatch.setattr(windows_friday, "_get_active_browser_hwnd", lambda keywords=None: None)
    monkeypatch.setattr(windows_friday, "get_all_contacts", lambda: {})

    handled, reply, meta = windows_friday.handle_directive(
        "FRIDAY, email bob@bad.invalid that the meeting moved to 3 PM")

    assert handled is True
    assert meta["receipt"]["status"] != "SENT"
    assert meta["success"] is False
    assert "successfully sent" not in reply


def test_the_registered_gmail_tool_reports_a_refusal_as_a_failure(monkeypatch):
    """send_gmail is live in the agent registry, so it answers to the model."""
    import friday.tools.builtin.email_tools as et
    from friday.tools.builtin.gmail_tools import SendGmailTool

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )

    result = SendGmailTool().execute(to_address="bob@bad.invalid", subject="S", body="B")

    assert result.is_error is True
    assert result.metadata.get("status") != "SENT"
    assert "successfully sent" not in result.content
    assert "550" in result.content, (
        "the refusal has to reach the caller, not just the log"
    )


def test_the_registered_gmail_tool_does_not_call_a_bare_draft_a_send(monkeypatch):
    """With no credentials it opens a draft and presses nothing."""
    import friday.tools.builtin.email_tools as et
    from friday.tools.builtin import gmail_tools as gt

    def empty():
        return SimpleNamespace(email_address=None, email_app_password=None)

    for target in (friday_config, et, gt):
        monkeypatch.setattr(target, "get_settings", empty)
    monkeypatch.setattr(gt, "webbrowser", type("W", (), {"open": staticmethod(lambda u: None)})())

    result = gt.SendGmailTool().execute(to_address="bob@bad.invalid", subject="S", body="B")

    assert result.is_error is True, "a draft that was never sent is not a successful send"
    assert result.metadata.get("status") == "NOT_SENT"


def test_an_accepted_recipient_still_earns_sent(monkeypatch):
    """The rule must not cost us the one true confirmation we can have."""
    import friday.tools.builtin.email_tools as et
    from friday.tools.builtin.gmail_tools import SendGmailTool

    _with_credentials(monkeypatch)
    monkeypatch.setattr(et.smtplib, "SMTP", _server_that_refuses({}))

    result = SendGmailTool().execute(to_address="alice@realwork.com", subject="S", body="B")

    assert result.is_error is False
    assert result.metadata.get("status") == "SENT"
    assert "successfully sent" in result.content


# --------------------------------------------------------------------------
# A refusal ends the attempt. It does not become somebody else's attempt.
# --------------------------------------------------------------------------


def test_a_refused_address_is_never_handed_to_a_second_transport(monkeypatch):
    """The server read the address and turned it down, so no browser opens.

    Opening a Gmail web compose for it buried the 550 under a draft the user
    never asked for and left the receipt claiming a web provider had answered.
    """
    import friday.tools.builtin.email_tools as et

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )
    opened: list = []
    monkeypatch.setattr(windows_friday, "open_url", lambda url: opened.append(url) or True)

    outcome = windows_friday.open_gmail(to="bob@bad.invalid", subject="S", body="B")

    assert not opened, f"a refused address was offered to the web anyway: {opened}"
    assert outcome.sent is False
    assert outcome.provider == "smtp.gmail.com", "SMTP answered, so SMTP is what the receipt records"
    assert "550" in outcome.detail and "bob@bad.invalid" in outcome.detail


def test_a_transport_that_never_judged_the_address_still_offers_the_fallback(monkeypatch):
    """Stopping the fallback must not cost the case it was actually for.

    An unreachable server has not refused anybody, so a draft is still the
    honest offer. Only a refusal ends the attempt.
    """
    _install(monkeypatch, driver=_Driver())
    outcome = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

    assert outcome.sent is False
    assert outcome.provider == "gmail_web"
    assert "draft" in outcome.detail.lower()


def test_the_receipt_records_the_transport_that_actually_answered(monkeypatch):
    """End to end: the refused run names the 550 and blames the right transport."""
    import friday.tools.builtin.email_tools as et

    _with_credentials(monkeypatch)
    monkeypatch.setattr(
        et.smtplib, "SMTP",
        _server_that_refuses({"bob@bad.invalid": (550, b"Mailbox unavailable")}),
    )
    opened: list = []
    monkeypatch.setattr(windows_friday, "open_url", lambda url: opened.append(url) or True)
    monkeypatch.setattr(windows_friday, "get_all_contacts", lambda: {})

    handled, reply, meta = windows_friday.handle_directive(
        "FRIDAY, email bob@bad.invalid that the meeting moved to 3 PM")

    assert handled is True
    assert not opened, "no compose window may open for an address the server refused"
    assert meta["receipt"]["status"] != "SENT"
    assert meta["receipt"]["provider"] == "smtp.gmail.com"
    assert meta["success"] is False
    assert "550" in reply, "the user is told what the server actually said"
    assert "successfully sent" not in reply


@pytest.mark.parametrize("directive", [ALICE, ALICE_ADDRESSED])
def test_no_web_send_ever_produces_a_sent_receipt(monkeypatch, directive):
    """The web path cannot observe Gmail, so it never earns SENT - by any route.

    Covered: the keystroke dispatched, a long wait, the compose window
    disappearing, and a name with no address. None of them is evidence.
    """
    _install(monkeypatch)
    monkeypatch.setattr(windows_friday, "get_all_contacts", lambda: {"alice": {"email": "alice@realwork.com"}})

    handled, reply, meta = windows_friday.handle_directive(directive)

    if "receipt" not in meta:
        assert "do not have an email address" in reply
        assert meta["success"] is False
        return
    assert meta["receipt"]["status"] == "NOT_CONFIRMED"
    assert meta["success"] is False
    for lie in ("dispatched", "Message sent", "has been sent", "check the Sent folder in Gmail"):
        if "pressed Ctrl+Enter" not in reply:
            assert lie not in reply, f"the reply still claims a send: {lie!r}"


# Measured, not argued: what a real Gmail compose does on Ctrl+Enter.
#
# Built-in browser panel, real keystroke, real Gmail account, 2026-10-02. A
# compose addressed to no-such-mailbox-zzz@invalid.invalid - a domain that
# cannot resolve - was accepted and sent. The page showed "Sending..." and
# then "Message sent / Undo / View message", and issued
# POST https://mail.google.com/sync/u/0/i/s. Gmail checks the shape of an
# address, not whether it delivers, so a well-formed address never produces a
# compose-stage failure to tell apart from a success.
#
# The only positive signal was that snackbar, and it lives in the page. The
# product reaches the browser through the Win32 window title alone, and after a
# send that title becomes "Inbox (230) - cometbrowser001@gmail.com - Gmail" -
# the same title a discarded draft leaves behind. Nothing the product can read
# separates a send from a dismissal, so the web path stays NOT_CONFIRMED.


def test_the_measured_post_send_desktop_state_is_still_not_a_send(monkeypatch):
    """Replays the real post-send desktop: window alive, title off Compose.

    This is the strongest evidence a genuine send leaves that the product can
    actually observe, and it is the same evidence a discarded draft leaves. It
    must not earn SENT.
    """
    state = {"title": "Compose Mail - cometbrowser001@gmail.com - Gmail"}

    class _SendsThenComposeCloses(_Driver):
        def hotkey(self, keys):
            sent = super().hotkey(keys)
            # The keystroke landed and Gmail sent: the compose window closed and
            # the title went back to the inbox view.
            state["title"] = "Inbox (230) - cometbrowser001@gmail.com - Gmail"
            return sent

    monkeypatch.setattr(windows_friday, "open_url", lambda url: True)
    monkeypatch.setattr(windows_friday, "_get_active_browser_hwnd", lambda keywords=None: 4242)
    monkeypatch.setattr(windows_friday, "_is_gmail_window", lambda h: "gmail" in state["title"].lower())

    import friday.devices.app_launcher as launcher
    import friday.vision.windows_input_driver as wdrv

    monkeypatch.setattr(launcher, "force_window_foreground", lambda h: True)
    monkeypatch.setattr(wdrv, "WindowsNativeInputDriver", lambda: _SendsThenComposeCloses())

    outcome = windows_friday.open_gmail(to="alice@realwork.com", subject="S", body="b")
    ok, message = outcome.sent, outcome.detail

    assert state["title"] == "Inbox (230) - cometbrowser001@gmail.com - Gmail", (
        "the test has to actually replay the post-send title"
    )
    assert ok is False, "a title that moved off Compose is not proof the mail left"
    assert "check the Sent folder" in message
    assert "NOT sent" in message


def test_the_compose_window_closing_is_not_evidence_of_a_send(monkeypatch):
    """Gmail's title does change after a send - and identically after a discard.

    So a vanished compose window cannot tell a send from a dismissal, and must
    never be read as proof that mail went out. The measurement above is why
    this stays decided rather than open.
    """
    _install(monkeypatch)
    monkeypatch.setattr(windows_friday, "get_all_contacts", lambda: {"alice": {"email": "alice@realwork.com"}})

    handled, reply, meta = windows_friday.handle_directive(ALICE)

    assert meta["receipt"]["status"] != "SENT"
    assert "check the Sent folder" in reply, (
        "the user is told where the truth can be found rather than given a guess"
    )


def test_a_name_with_no_known_address_declines_rather_than_guessing(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(windows_friday, "_lookup_contact_email", lambda name: None)

    handled, reply, meta = windows_friday.handle_directive(ALICE)

    assert handled is True
    assert "do not have an email address" in reply
    assert "receipt" not in meta, "a declined send must not leave a receipt behind"
    assert meta["success"] is False
    for guess in ("example.com", "@example"):
        assert guess not in reply, f"the reply invented an address: {guess!r}"


def test_a_saved_contact_address_is_used_when_one_exists(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(windows_friday, "get_all_contacts", lambda: {"alice": {"email": "alice@realwork.com"}})
    sent: list = []
    monkeypatch.setattr(windows_friday, "open_gmail", lambda **kw: sent.append(kw) or GmailSend(False, "draft", "gmail_web"))

    handled, reply, meta = windows_friday.handle_directive(ALICE)

    assert handled is True
    assert sent[0]["to"] == "alice@realwork.com"
    assert meta["receipt"]["recipient"] == "alice@realwork.com"


def test_the_receipt_records_the_provider_actually_used(monkeypatch):
    """A web send must not name an SMTP provider it never used."""
    _install(monkeypatch)

    handled, reply, meta = windows_friday.handle_directive(ALICE_ADDRESSED)

    assert meta["receipt"]["provider"] == "gmail_web"
    assert meta["receipt"]["recipient"] == "alice@realwork.com"
    assert "the meeting moved to 3 pm" in meta["receipt"]["body"].lower()
    # The verdict is asserted, not its casing: what the reader must not be able
    # to miss is that this was not a send.
    assert "not sent" in reply.lower()
    assert "NOT_CONFIRMED" in reply, "the receipt status belongs in the reply too"


def test_a_confirmed_send_produces_a_sent_receipt_end_to_end(monkeypatch):
    _install(monkeypatch, smtp=(True, "250 OK"))

    handled, reply, meta = windows_friday.handle_directive(ALICE_ADDRESSED)

    assert handled is True
    assert meta["success"] is True
    assert meta["receipt"]["status"] == "SENT"
    assert meta["receipt"]["provider"] == "smtp.gmail.com"
    assert "sent and confirmed" in reply