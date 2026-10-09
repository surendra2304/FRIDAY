"""Verified side effects.

FRIDAY's value depends on one property above all others: when it says a thing
happened, the thing happened. The tool layer drifted away from that in a way
that was invisible to unit tests, because the *return shapes* were all correct:

* ``launch_application`` built a shell command and called
  ``subprocess.Popen(shell=True)``. ``Popen`` succeeds when the *shell* starts,
  so on a machine with no ``notepad.exe`` the shell exited 127 into an unread
  pipe and the caller was told ``Launched 'notepad.exe'.`` - a success claim for
  a program that does not exist. Pinning that with a test is only possible if
  the check lives somewhere testable, which is what this module is for.
* ``open_whatsapp`` / ``send_whatsapp_message`` called ``webbrowser.open`` and
  discarded the boolean. ``webbrowser.open`` returns ``False`` precisely when no
  browser accepted the URL, and the tool claimed the browser had opened anyway.
  ``open_website`` and ``youtube`` already checked; the two WhatsApp tools did
  not, so the same user action produced opposite truthfulness depending on which
  tool the model chose.

Both are silent - no exception, no log line, no failing test - and both are
user-visible within one sentence of the reply. Everything here exists so a
claim about the world is produced by the same call that touches the world.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import shlex
import sys
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("core.effects")

#: How long a just-started process is watched before it is called "launched".
#: Long enough for a shell to fail on a missing binary (milliseconds), short
#: enough not to stall a tool call that legitimately runs for minutes.
_LAUNCH_SETTLE_SECONDS = 0.4

#: Cap on captured output so a runaway command cannot fill memory.
_MAX_CAPTURE = 4000

_POSIX_BROWSERS = (
    "xdg-open",
    "x-www-browser",
    "firefox",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "brave-browser",
    "microsoft-edge",
)


@dataclass(frozen=True)
class EffectOutcome:
    """The result of trying to change something in the world.

    ``ok`` means the effect was confirmed started or confirmed delivered - never
    merely "the API did not raise". ``detail`` is a sentence safe to show the
    user; ``evidence`` carries what the check actually observed.
    """

    ok: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, **self.evidence}


def _clip(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= _MAX_CAPTURE:
        return text
    return text[:_MAX_CAPTURE] + "... [truncated]"


def browser_available() -> bool:
    """Whether this machine has a browser FRIDAY could hand a URL to.

    Windows resolves the default handler through the registry, so ``webbrowser``
    is trusted there. On POSIX ``webbrowser`` falls back to a browser that may
    not exist; the check is against the executable itself.
    """
    if sys.platform.startswith("win"):
        return True
    if os.environ.get("BROWSER"):
        return True
    return any(shutil.which(name) for name in _POSIX_BROWSERS)


def open_url_verified(url: str) -> EffectOutcome:
    """Open ``url`` and report what the browser layer actually said.

    ``webbrowser.open`` returns a boolean that is the only available signal for
    "a browser took this URL". Discarding it is what let a headless machine
    report a page as opened; it is checked here for every caller.
    """
    if not url:
        return EffectOutcome(False, "No URL was given, so nothing was opened.", {"url": url})

    try:
        opened = webbrowser.open(url)
    except Exception as exc:  # pragma: no cover - platform-specific surprises
        logger.warning("webbrowser.open failed for %s: %s", url, exc)
        return EffectOutcome(
            False,
            f"The system could not open a browser for {url}: {exc}",
            {"url": url, "error": str(exc)},
        )

    if not opened:
        reason = (
            "no browser is installed or configured on this machine"
            if not browser_available()
            else "the default browser did not accept the request"
        )
        return EffectOutcome(
            False,
            f"Could not open {url}: {reason}. Nothing was opened.",
            {"url": url, "opened": False, "browser_available": browser_available()},
        )

    return EffectOutcome(
        True,
        f"Opened {url} in the default browser.",
        {"url": url, "opened": True, "browser_available": browser_available()},
    )


def launch_argv_verified(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    settle_seconds: float = _LAUNCH_SETTLE_SECONDS,
    env: dict[str, str] | None = None,
    creationflags: int = 0,
) -> EffectOutcome:
    """Start an executable argument vector without a shell and verify its result.

    GUI launchers should pass an argv list instead of shell-quoting a path. A
    still-running process counts as launched; an already-exited process only
    counts when it exited with status zero.
    """
    args = [str(value) for value in argv]
    if not args or not args[0].strip():
        return EffectOutcome(False, "No executable was given, so nothing was launched.", {"argv": args})

    display = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            creationflags=creationflags,
        )
    except Exception as exc:
        logger.warning("Could not start %r: %s", display, exc)
        return EffectOutcome(
            False,
            f"Could not start {display}: {exc}",
            {"argv": args, "error": str(exc)},
        )

    try:
        returncode = proc.wait(timeout=max(0.05, settle_seconds))
    except subprocess.TimeoutExpired:
        return EffectOutcome(
            True,
            f"Started {args[0]} and the process is still running.",
            {"argv": args, "running": True, "pid": proc.pid},
        )
    except Exception as exc:  # pragma: no cover - defensive
        return EffectOutcome(
            True,
            f"Started {args[0]}.",
            {"argv": args, "running": True, "pid": proc.pid, "wait_error": str(exc)},
        )

    stdout, stderr = "", ""
    try:
        stdout, stderr = proc.communicate(timeout=1.0)
    except Exception:  # pragma: no cover - defensive
        pass

    evidence: dict[str, Any] = {"argv": args, "returncode": returncode}
    if stdout:
        evidence["stdout"] = _clip(stdout)
    if stderr:
        evidence["stderr"] = _clip(stderr)
    if returncode == 0:
        return EffectOutcome(True, f"Ran {display} (it finished with status 0).", evidence)

    reason = _clip(stderr) or _clip(stdout) or f"exit status {returncode}"
    return EffectOutcome(False, f"{display} did not run: {reason}", {**evidence, "reason": reason})


def launch_process_verified(
    command: str,
    *,
    cwd: str | None = None,
    settle_seconds: float = _LAUNCH_SETTLE_SECONDS,
    env: dict[str, str] | None = None,
) -> EffectOutcome:
    """Start ``command`` through a shell and confirm a process is really there.

    A command that is still running after ``settle_seconds`` was launched. A
    command that already exited is only a success if it exited **zero**; a
    non-zero exit means the shell could not run the program - the exact case
    that produced ``Launched 'notepad.exe'.`` on a machine that has no notepad -
    and the captured stderr is returned as the reason.
    """
    if not command or not command.strip():
        return EffectOutcome(False, "No command was given, so nothing was launched.", {})

    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except Exception as exc:
        logger.warning("Could not start %r: %s", command, exc)
        return EffectOutcome(
            False,
            f"Could not start {command}: {exc}",
            {"command": command, "error": str(exc)},
        )

    returncode: int | None = None
    try:
        returncode = proc.wait(timeout=max(0.05, settle_seconds))
    except subprocess.TimeoutExpired:
        # Still alive: this is what a real launch looks like.
        return EffectOutcome(
            True,
            f"Launched {command}.",
            {"command": command, "running": True, "pid": proc.pid},
        )
    except Exception as exc:  # pragma: no cover - defensive
        return EffectOutcome(
            True,
            f"Launched {command}.",
            {"command": command, "running": True, "pid": proc.pid, "wait_error": str(exc)},
        )

    stdout, stderr = "", ""
    try:
        stdout, stderr = proc.communicate(timeout=1.0)
    except Exception:  # pragma: no cover - defensive
        pass

    evidence: dict[str, Any] = {"command": command, "returncode": returncode}
    if stdout:
        evidence["stdout"] = _clip(stdout)
    if stderr:
        evidence["stderr"] = _clip(stderr)

    if returncode == 0:
        # Ran to completion successfully, e.g. a launcher script or a CLI that
        # hands the work to a service and returns.
        return EffectOutcome(
            True,
            f"Ran {command} (it finished with status 0).",
            evidence,
        )

    reason = _clip(stderr) or _clip(stdout) or f"exit status {returncode}"
    return EffectOutcome(
        False,
        f"{command} did not run: {reason}",
        {**evidence, "reason": reason},
    )


def python_module_command(module: str, *args: str) -> list[str]:
    """Build ``python -m <module> ...`` for the interpreter running FRIDAY.

    Tools that shelled out to a bare ``pytest`` relied on the user's PATH having
    a console script next to a *different* interpreter, so "run the tests" failed
    with ``No such file or directory: 'pytest'`` on a machine where FRIDAY's own
    venv had pytest installed and the suite was one import away from running.
    """
    return [sys.executable, "-m", module, *args]


def pytest_command(*args: str) -> list[str]:
    """``python -m pytest`` with FRIDAY's own interpreter."""
    return python_module_command("pytest", *args)


def missing_module_hint(module: str) -> str:
    """An honest explanation for "the tool this needs is not installed"."""
    try:
        import importlib.util

        if importlib.util.find_spec(module) is None:
            return (
                f"'{module}' is not installed in the Python environment running FRIDAY "
                f"({sys.executable}). Install it and try again."
            )
    except Exception:  # pragma: no cover - defensive
        return ""
    return ""
