"""Interactive CLI implementation of BaseAuthorizer for FRIDAY.

An interactive authorizer may only prompt when it has somewhere to prompt. Found by
driving the API: the server was built with this class, a SENSITIVE tool call printed
"[AUTHORIZATION REQUEST] ... Authorize execution? [y/N]:" into the server's log, read
a stdin nobody was typing into, and reported the resulting EOF as a refusal — or, on
a deployment where stdin stays open, would have blocked the request thread for as long
as the pipe lived. A question a human cannot see is not a question, and silence is not
consent.
"""

import sys
from typing import Any

from friday.core.auth import BaseAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
)


def _prompt_user(prompt_str: str) -> str:
    """Prompt user for input while safely pausing any active Rich status spinner."""
    active_spinner = None
    try:
        from friday.cli.main import _active_status
        if _active_status and _active_status.get("obj"):
            active_spinner = _active_status["obj"]
            active_spinner.stop()
    except Exception:
        pass

    try:
        return input(prompt_str)
    finally:
        if active_spinner:
            try:
                active_spinner.start()
            except Exception:
                pass


#: The prompt function that reads *this process's* stdin. Kept by identity so the
#: terminal guard can tell "nobody can answer this" from "somebody installed another
#: way to ask" — a UI, an automation harness, a test double. An injected channel is
#: not this process's terminal, so the terminal check does not speak for it.
_terminal_prompt_user = _prompt_user


class CLIAuthorizer(BaseAuthorizer):
    """Interactive CLI authorizer that supports autonomous mode or prompts for confirmations."""

    def __init__(self, authorizer: Any | None = None, auto_approve_all: bool | None = None) -> None:
        super().__init__(authorizer=authorizer)
        from friday.core.config import get_settings

        self.settings = get_settings()
        self._auto_approve_all_override = auto_approve_all

    @property
    def auto_approve_all(self) -> bool:
        """Read the current shared mode unless this instance has an explicit override."""
        if self._auto_approve_all_override is not None:
            return self._auto_approve_all_override
        from friday.core.config import get_settings

        return bool(get_settings().autonomous_mode)

    @property
    def full_access(self) -> bool:
        """Read the current full-access setting rather than a stale constructor snapshot."""
        from friday.core.config import get_settings

        return bool(get_settings().full_access_mode)

    @staticmethod
    def _has_a_terminal() -> bool:
        """Whether a human could actually answer a prompt here."""
        try:
            return bool(sys.stdin) and sys.stdin.isatty()
        except Exception:
            return False

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        # SAFE work is automatic. Explicit runtime modes may auto-approve SENSITIVE
        # actions, but DANGEROUS actions always reach the confirmation boundary.
        if request.safety_level == SafetyLevel.SAFE or (
            request.safety_level == SafetyLevel.SENSITIVE and (self.auto_approve_all or self.full_access)
        ):
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Autonomous laptop controller execution approved.",
                capability=self.issue_capability_for_request(request),
            )

        # Print authorization box headers and details
        border = "=" * 72
        divider = "-" * 72

        # Nothing to ask with: say so, and do not read stdin. This is a refusal, not a
        # cancellation, because no human was asked and none declined. This applies only
        # while confirmations come from this process's own stdin; a caller that installs
        # its own prompt function (a UI, a harness, a test) still gets asked through it,
        # so the interactive protocol stays testable and the server stays fail-closed.
        if _prompt_user is _terminal_prompt_user and not self._has_a_terminal():
            return AuthorizationResponse(
                decision=AuthorizationDecision.DENIED,
                reason=(
                    f"Safety Block: no interactive terminal is attached, so the confirmation "
                    f"for tool '{request.tool_name}' cannot be asked. Nothing was run."
                ),
            )

        print(f"\n{border}")

        # 2. Handle SENSITIVE confirmation
        if request.safety_level == SafetyLevel.SENSITIVE:
            print(f"[AUTHORIZATION REQUEST] Safety Level: {request.safety_level.value}")
            print(f"Tool      : {request.tool_name}")
            if request.affected_resource:
                print(f"Resource  : {request.affected_resource}")
            print("Arguments :")
            for k, v in request.arguments.items():
                print(f"  * {k}: {v}")
            print(divider)
            
            try:
                user_choice = _prompt_user("Authorize execution? [y/N]: ").strip().lower()
                if user_choice in ("y", "yes"):
                    return AuthorizationResponse(
                        decision=AuthorizationDecision.APPROVED,
                        reason="Explicit CLI user approval granted.",
                        capability=self.issue_capability_for_request(request),
                    )
                else:
                    return AuthorizationResponse(
                        decision=AuthorizationDecision.DENIED,
                        reason="CLI user rejected SENSITIVE execution request.",
                    )
            except (KeyboardInterrupt, EOFError):
                print("\n[Cancelled]")
                return AuthorizationResponse(
                    decision=AuthorizationDecision.CANCELLED,
                    reason="CLI user cancelled the prompt session.",
                )

        # 3. Handle DANGEROUS confirmation (requires typing 'CONFIRM')
        if request.safety_level == SafetyLevel.DANGEROUS:
            if self.auto_approve_all or self.full_access:
                print("DANGEROUS actions always require explicit confirmation, even in autonomous mode.")
            print("WARNING: [DANGEROUS OPERATION REQUESTED]")
            print(f"Tool      : {request.tool_name}")
            if request.affected_resource:
                print(f"Resource  : {request.affected_resource}")
            print("Arguments :")
            for k, v in request.arguments.items():
                print(f"  * {k}: {v}")
            print(divider)
            
            try:
                print("To authorize this DANGEROUS action, please type 'CONFIRM' (case-sensitive):")
                user_choice = _prompt_user("Response: ").strip()
                if user_choice == "CONFIRM":
                    return AuthorizationResponse(
                        decision=AuthorizationDecision.APPROVED,
                        reason="Explicit DANGEROUS verification accepted.",
                        capability=self.issue_capability_for_request(request),
                    )
                else:
                    return AuthorizationResponse(
                        decision=AuthorizationDecision.DENIED,
                        reason="CLI user failed the DANGEROUS verification prompt.",
                    )
            except (KeyboardInterrupt, EOFError):
                print("\n[Cancelled]")
                return AuthorizationResponse(
                    decision=AuthorizationDecision.CANCELLED,
                    reason="CLI user cancelled the prompt session.",
                )

        # Catch-all fallback
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason="Unrecognized safety level configuration encountered.",
        )
