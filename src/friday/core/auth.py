from abc import ABC, abstractmethod
from typing import Any, Optional
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
)
from friday.core.exceptions import SecurityError
from friday.security.authorization import ToolAuthorizer, ToolAuthorizationCapability, tool_authorizer


class BaseAuthorizer(ABC):
    """Abstract Base Class for validating and authorizing tool execution requests."""

    def __init__(self, authorizer: Optional[ToolAuthorizer] = None) -> None:
        self.tool_authorizer: ToolAuthorizer = authorizer or tool_authorizer

    def issue_capability_for_request(self, request: AuthorizationRequest) -> ToolAuthorizationCapability:
        """Generate a signed, single-use, time-bounded authorization capability for an approved request."""
        return self.tool_authorizer.issue_capability(
            tool_name=request.tool_name,
            arguments=request.arguments,
            safety_level=request.safety_level,
            tool_call_id=request.tool_call_id or "",
            purpose=request.purpose or "",
            affected_resource=request.affected_resource or "",
        )

    @abstractmethod
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        """Evaluate if the requested tool execution is authorized.

        Args:
            request: The tool execution authorization details.

        Returns:
            AuthorizationResponse containing the decision, optional reason, and capability.
        """
        pass


class DefaultSecureAuthorizer(BaseAuthorizer):
    """Secure default authorizer that automatically executes SAFE tools but denies others."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        if request.safety_level == SafetyLevel.SAFE:
            cap = self.issue_capability_for_request(request)
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
                capability=cap,
            )
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason=(
                f"Safety Block: Tool '{request.tool_name}' requires explicit user confirmation. "
                f"No interactive authorizer was configured."
            ),
        )


class AutoApproveAuthorizer(BaseAuthorizer):
    """TEST-ONLY authorizer implementation for isolated automated unit/integration tests.

    CRITICAL SECURITY INVARIANT:
    This authorizer is strictly prohibited in production mode.
    Attempting to instantiate this authorizer in production or without explicit test acknowledgment
    raises a SecurityError.
    """

    def __init__(
        self,
        test_only_explicit_ack: bool = False,
        allow_dangerous_for_testing: bool = False,
        allowed_tools: Optional[Any] = None,
        authorizer: Optional[ToolAuthorizer] = None,
    ) -> None:
        import os
        # 1. Reject in production environments
        env = os.getenv("FRIDAY_ENV", "").strip().lower()
        if env in ("prod", "production"):
            raise SecurityError("AutoApproveAuthorizer is strictly prohibited in production environment!")

        # 2. Require explicit test acknowledgment
        if not test_only_explicit_ack:
            raise SecurityError(
                "AutoApproveAuthorizer is strictly test-only and requires explicit parameter: "
                "test_only_explicit_ack=True or use AutoApproveAuthorizer.create_for_testing()."
            )

        super().__init__(authorizer=authorizer)
        self.allow_dangerous_for_testing: bool = allow_dangerous_for_testing
        self.allowed_tools: Optional[set] = set(allowed_tools) if allowed_tools is not None else None

    @classmethod
    def create_for_testing(
        cls,
        allow_dangerous: bool = False,
        allowed_tools: Optional[Any] = None,
        authorizer: Optional[ToolAuthorizer] = None,
    ) -> "AutoApproveAuthorizer":
        """Explicit test-only factory constructor for isolated testing harnesses."""
        return cls(
            test_only_explicit_ack=True,
            allow_dangerous_for_testing=allow_dangerous,
            allowed_tools=allowed_tools,
            authorizer=authorizer,
        )

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        # Check tool allowlist if configured
        if self.allowed_tools is not None and request.tool_name not in self.allowed_tools:
            return AuthorizationResponse(
                decision=AuthorizationDecision.DENIED,
                reason=f"Test-only AutoApproveAuthorizer rejected tool '{request.tool_name}' (not in allowed test tools).",
            )

        # Protect dangerous operations unless explicitly enabled for testing
        if request.safety_level == SafetyLevel.DANGEROUS and not self.allow_dangerous_for_testing:
            return AuthorizationResponse(
                decision=AuthorizationDecision.DENIED,
                reason=(
                    f"Test-only AutoApproveAuthorizer safety guard: DANGEROUS tool '{request.tool_name}' "
                    "cannot be auto-approved without allow_dangerous_for_testing=True."
                ),
            )

        cap = self.issue_capability_for_request(request)
        return AuthorizationResponse(
            decision=AuthorizationDecision.APPROVED,
            reason=f"Test-only auto-approved execution of '{request.tool_name}'.",
            capability=cap,
        )


class AutoDenyAuthorizer(BaseAuthorizer):
    """Authorizer implementation that denies all SENSITIVE and DANGEROUS execution requests."""

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        if request.safety_level == SafetyLevel.SAFE:
            cap = self.issue_capability_for_request(request)
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="Automatic execution approved for SAFE tools.",
                capability=cap,
            )
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason=f"Safety Block: AutoDeny policy rejected execution of '{request.tool_name}'.",
        )
