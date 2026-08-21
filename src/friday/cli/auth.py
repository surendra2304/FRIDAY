"""Interactive CLI implementation of BaseAuthorizer for FRIDAY."""

from friday.core.auth import BaseAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
)


class CLIAuthorizer(BaseAuthorizer):
    """Interactive CLI authorizer that prompts the user for SENSITIVE and DANGEROUS confirmations."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        # 1. Automatic approval for SAFE tools
        if request.safety_level == SafetyLevel.SAFE:
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
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
                user_choice = input("Authorize execution? [y/N]: ").strip().lower()
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
                user_choice = input("Response: ").strip()
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
