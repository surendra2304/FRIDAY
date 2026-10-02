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

import threading
import time
from types import SimpleNamespace

import pytest

from friday.core import config as friday_config
from friday.devices import windows_friday as wf
from friday.devices.windows_friday import windows_friday

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
            return smtp

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

    ok, _ = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
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

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

    assert not log, "a keystroke was sent into a window that is not Gmail"
    assert "could not press send" in msg
    assert ok is False


def test_a_gmail_window_is_still_acted_on(monkeypatch):
    """The window check must not stop the send when Gmail really is the window."""
    log: list = []
    _install(monkeypatch, driver=_Driver(log=log))

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

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
    ok, _ = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
    assert time.monotonic() - started < 2.0, "waited the full budget for a window already on screen"
    assert ok is False

    _install(monkeypatch, hwnd=None)  # never appears
    monkeypatch.setattr(wf, "_GMAIL_AUTOSEND_TIMEOUT_SECONDS", 0.5)
    started = time.monotonic()
    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")
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

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

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

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

    assert ok is False
    assert "NOT sent" in msg or "NOT SENT" in msg


def test_a_failure_reason_reaches_the_user_rather_than_only_the_log(monkeypatch):
    """The blocked driver is a real condition on this machine; say why."""
    _install(monkeypatch, driver=_Driver(raises=OSError("dll load failed")))

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

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

    ok, msg = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

    assert ok is True
    assert "sent successfully" in msg


@pytest.mark.parametrize("smtp", [(False, "535 auth failed"), RuntimeError("no network")])
def test_an_smtp_failure_falls_through_without_claiming_a_send(monkeypatch, smtp):
    _install(monkeypatch, smtp=smtp)

    ok, _ = windows_friday.open_gmail(to="a@b.com", subject="S", body="b")

    assert ok is False


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

    ok, message = windows_friday.open_gmail(to="alice@realwork.com", subject="S", body="b")

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
    monkeypatch.setattr(windows_friday, "open_gmail", lambda **kw: sent.append(kw) or (False, "draft"))

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
    assert "NOT SENT" in reply


def test_a_confirmed_send_produces_a_sent_receipt_end_to_end(monkeypatch):
    _install(monkeypatch, smtp=(True, "250 OK"))

    handled, reply, meta = windows_friday.handle_directive(ALICE_ADDRESSED)

    assert handled is True
    assert meta["success"] is True
    assert meta["receipt"]["status"] == "SENT"
    assert meta["receipt"]["provider"] == "smtp.gmail.com"
    assert "sent and confirmed" in reply