"""Interactive CLI implementation of BaseAuthorizer for FRIDAY."""

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


class CLIAuthorizer(BaseAuthorizer):
    """Interactive CLI authorizer that supports autonomous mode or prompts for confirmations."""

    def __init__(self, authorizer: Any | None = None, auto_approve_all: bool | None = None) -> None:
        super().__init__(authorizer=authorizer)
        from friday.core.config import get_settings
        self.settings = get_settings()
        if auto_approve_all is not None:
            self.auto_approve_all = auto_approve_all
        else:
            self.auto_approve_all = getattr(self.settings, "autonomous_mode", False)
        self.full_access = getattr(self.settings, "full_access_mode", False)

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        # Only safe tools auto-approve by default. Consequential actions require a
        # prompt unless the owner explicitly opts into autonomous/full-access mode.
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
