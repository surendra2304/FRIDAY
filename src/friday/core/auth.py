"""Authorization interfaces and default implementations for FRIDAY."""

from abc import ABC, abstractmethod
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
)


class BaseAuthorizer(ABC):
    """Abstract Base Class for validating and authorizing tool execution requests."""

    @abstractmethod
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        """Evaluate if the requested tool execution is authorized.

        Args:
            request: The tool execution authorization details.

        Returns:
            AuthorizationResponse containing the decision and optional reason.
        """
        pass


class DefaultSecureAuthorizer(BaseAuthorizer):
    """Secure default authorizer that automatically executes SAFE tools but denies others."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        if request.safety_level == SafetyLevel.SAFE:
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
            )
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason=(
                f"Safety Block: Tool '{request.tool_name}' requires explicit user confirmation. "
                f"No interactive authorizer was configured."
            ),
        )


class AutoApproveAuthorizer(BaseAuthorizer):
    """Authorizer implementation that automatically approves all requested operations."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(
            decision=AuthorizationDecision.APPROVED,
            reason=f"Automatically approved execution of '{request.tool_name}'.",
        )


class AutoDenyAuthorizer(BaseAuthorizer):
    """Authorizer implementation that denies all SENSITIVE and DANGEROUS execution requests."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        if request.safety_level == SafetyLevel.SAFE:
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
            )
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason=f"Safety Block: AutoDeny policy rejected execution of '{request.tool_name}'.",
        )
