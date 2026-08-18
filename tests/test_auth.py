"""Tests for the tool authorization and confirmation system."""

from typing import Any, Dict, List, Optional
import pytest
from friday.agent.agent import FridayAgent
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer, AutoApproveAuthorizer, AutoDenyAuthorizer
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
    Role,
    Message,
    ToolCall,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.llm.mock_provider import MockLLMProvider


class MockDangerousTool(BaseTool):
    name = "delete_database"
    description = "Deletes database files permanently"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {
            "db_name": {"type": "string"},
        },
        "required": ["db_name"],
    }

    def execute(self, db_name: str, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Database '{db_name}' successfully deleted.",
            is_error=False,
            safety_level=self.safety_level,
        )


class MockSensitiveTool(BaseTool):
    name = "write_settings"
    description = "Modifies active application settings"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
    }

    def execute(self, key: str, value: str, **kwargs: Any) -> ToolResult:
        return ToolResult(
            name=self.name,
            content=f"Settings updated: {key}={value}",
            is_error=False,
            safety_level=self.safety_level,
        )


class CustomTestAuthorizer(BaseAuthorizer):
    """Authorizer with preset decisions for testing."""

    def __init__(self, decision: AuthorizationDecision, reason: str = "Test decision"):
        self.decision = decision
        self.reason = reason
        self.requested: List[AuthorizationRequest] = []

    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        self.requested.append(request)
        return AuthorizationResponse(decision=self.decision, reason=self.reason)


# --- 1. SAFE automatic execution ---
def test_safe_tool_auto_executes():
    # Registry with get_system_info (SAFE)
    agent = FridayAgent(
        settings=Settings(env="testing"),
        authorizer=DefaultSecureAuthorizer()  # Safe tools auto-approved
    )
    
    # Run a safe command
    response = agent.process_message("Check system info")
    assert response.is_done
    assert "System Diagnostics Report" in response.content


# --- 2. SENSITIVE approved execution ---
def test_sensitive_approved_execution():
    auth = CustomTestAuthorizer(AuthorizationDecision.APPROVED, "Approved by admin")
    reg = ToolRegistry()
    tool = MockSensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={"key": "theme", "value": "dark"})],
            )
        return Message(role=Role.ASSISTANT, content="Completed setting key.")
        
    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Set theme to dark")
    assert response.is_done
    
    # Verify authorizer received authorization request
    assert len(auth.requested) == 1
    assert auth.requested[0].tool_name == "write_settings"
    assert auth.requested[0].safety_level == SafetyLevel.SENSITIVE
    assert auth.requested[0].arguments == {"key": "theme", "value": "dark"}
    
    # Check that tool results are present and successful
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert not response.tool_results[0].is_error
    assert "Settings updated" in response.tool_results[0].content


# --- 3. SENSITIVE denied execution ---
def test_sensitive_denied_execution():
    auth = CustomTestAuthorizer(AuthorizationDecision.DENIED, "Denied for security reasons")
    reg = ToolRegistry()
    tool = MockSensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={"key": "theme", "value": "dark"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Set theme to dark")
    assert response.is_done
    
    # Verify execution was blocked and error ToolResult returned
    assert len(auth.requested) == 1
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error
    assert "Authorization Block" in response.tool_results[0].content
    assert "Denied for security reasons" in response.tool_results[0].content


# --- 4. DANGEROUS approved execution ---
def test_dangerous_approved_execution():
    auth = CustomTestAuthorizer(AuthorizationDecision.APPROVED, "Risk approved")
    reg = ToolRegistry()
    tool = MockDangerousTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Deleting database...",
                tool_calls=[ToolCall(id="c1", name="delete_database", arguments={"db_name": "prod_db"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Delete prod_db")
    assert response.is_done
    assert len(auth.requested) == 1
    assert auth.requested[0].tool_name == "delete_database"
    assert auth.requested[0].safety_level == SafetyLevel.DANGEROUS
    
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert not response.tool_results[0].is_error
    assert "successfully deleted" in response.tool_results[0].content


# --- 5. DANGEROUS denied execution ---
def test_dangerous_denied_execution():
    auth = CustomTestAuthorizer(AuthorizationDecision.DENIED, "Access denied")
    reg = ToolRegistry()
    tool = MockDangerousTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Deleting...",
                tool_calls=[ToolCall(id="c1", name="delete_database", arguments={"db_name": "prod_db"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Delete prod_db")
    assert response.is_done
    assert len(auth.requested) == 1
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error
    assert "Authorization Block" in response.tool_results[0].content


# --- 6. cancelled confirmation ---
def test_cancelled_confirmation():
    auth = CustomTestAuthorizer(AuthorizationDecision.CANCELLED, "CLI window closed")
    reg = ToolRegistry()
    tool = MockSensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={"key": "theme", "value": "dark"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Set theme")
    assert response.is_done
    assert len(auth.requested) == 1
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error
    assert "was CANCELLED" in response.tool_results[0].content


# --- 7. invalid authorization response ---
def test_invalid_authorization_response():
    auth = CustomTestAuthorizer(AuthorizationDecision.EXPIRED, "Timeout waiting for response")
    reg = ToolRegistry()
    tool = MockSensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={"key": "theme", "value": "dark"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Set theme")
    assert response.is_done
    assert len(auth.requested) == 1
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error
    assert "was EXPIRED" in response.tool_results[0].content


# --- 8. tool validation before authorization ---
def test_validation_happens_before_authorization():
    auth = CustomTestAuthorizer(AuthorizationDecision.APPROVED)
    reg = ToolRegistry()
    tool = MockSensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Missing required arguments 'key' and 'value' -> validation error
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    response = agent.process_message("Set theme")
    assert response.is_done
    
    # 1. Validation fails, so authorizer MUST NOT be queried
    assert len(auth.requested) == 0
    
    # 2. Rejection ToolResult is generated
    assert response.tool_results is not None
    assert len(response.tool_results) == 1
    assert response.tool_results[0].is_error
    assert "Invalid arguments" in response.tool_results[0].content


# --- 9. execution after authorization only ---
def test_execution_after_authorization_only():
    auth = CustomTestAuthorizer(AuthorizationDecision.DENIED)
    
    # Create a spy tool to monitor execution
    execution_triggered = False
    
    class SpySensitiveTool(MockSensitiveTool):
        def execute(self, key: str, value: str, **kwargs: Any) -> ToolResult:
            nonlocal execution_triggered
            execution_triggered = True
            return super().execute(key, value, **kwargs)
            
    reg = ToolRegistry()
    tool = SpySensitiveTool()
    reg.register(tool)
    
    call_count = 0
    def mock_responder(messages: List[Message], tools: Optional[List[Dict[str, Any]]]) -> Message:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Message(
                role=Role.ASSISTANT,
                content="Setting key...",
                tool_calls=[ToolCall(id="c1", name="write_settings", arguments={"key": "theme", "value": "dark"})],
            )
        return Message(role=Role.ASSISTANT, content="Done.")

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(custom_responder=mock_responder),
        tool_registry=reg,
        authorizer=auth
    )
    
    agent.process_message("Set theme")
    
    # Verifies tool execute method was never called because auth was DENIED
    assert not execution_triggered
