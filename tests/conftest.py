import sys
from pathlib import Path

import pytest

try:
    pass  # Initialize pandas C-extensions before test monkeypatching
except Exception:
    pass

# Ensure src/ is on Python search path
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import os
from unittest.mock import patch

from friday.auth.request_accounting import (
    BudgetLimits,
    request_accountant,
)
from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def reset_accounting_and_pool_state():
    """Ensure clean accounting and credential pool state for every single test."""
    from friday.core.config import get_settings
    get_settings(reload=True)
    request_accountant.reset()
    request_accountant.limits = BudgetLimits(
        max_requests_per_task=100,
        max_requests_per_session=500,
        max_requests_per_hour=1000,
        max_requests_per_day=5000,
        max_consecutive_failed_calls=10,
        max_vision_perceptions_per_task=50,
    )
    yield
    request_accountant.reset()
    request_accountant.limits = BudgetLimits()


@pytest.fixture(autouse=True, scope="session")
def isolate_test_environment():
    """Ensure tests never load real .env keys or accidentally hit real embedding APIs."""
    os.environ["FRIDAY_EMBEDDING_PROVIDER"] = "none"
    os.environ["FRIDAY_GEMINI_API_KEY"] = "MOCK_GEMINI_API_KEY_FOR_TESTING_ONLY"
    os.environ["FRIDAY_LLM_API_KEY"] = "MOCK_OPENAI_API_KEY_FOR_TESTING_ONLY"
    os.environ["FRIDAY_AUTONOMOUS_MODE"] = "false"
    os.environ["FRIDAY_FULL_ACCESS_MODE"] = "false"
    
    # Patch config so `Settings()` defaults to NOT loading `.env`
    with patch("friday.core.config.resolve_env_file") as mock_resolve:
        mock_resolve.return_value = Path("/dev/null/fake.env")
        yield
@pytest.fixture
def mock_settings() -> Settings:
    """Fixture providing clean default settings for testing."""
    return Settings(
        env="testing",
        log_level="DEBUG",
        log_file=None,
        llm_provider="mock",
        llm_model="mock-gpt",
        llm_api_key="TEST_OPENAI_API_KEY",
        embedding_provider="none",
        memory_backend="in_memory",
        memory_max_messages=10,
        agent_name="FRIDAY-TEST",
        user_name="Surendra",
    )


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    """Fixture providing deterministic mock LLM provider."""
    return MockLLMProvider(model="mock-test")


@pytest.fixture
def memory_buffer() -> InMemoryConversationMemory:
    """Fixture providing memory buffer with capacity of 4 messages."""
    return InMemoryConversationMemory(max_messages=4)


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Fixture providing tool registry loaded with SystemInfoTool."""
    reg = ToolRegistry()
    reg.register(SystemInfoTool())
    return reg


# The cognition layer remembers things: each agent owns a mind (a capability
# ledger) and the fleet shares one episodic memory. Both persist to disk by
# default, which is the point in production — and exactly wrong in a test suite,
# where a ledger written by one run would silently change the next one's answers.
# `tmp_path_factory` keeps every write inside the test session.
@pytest.fixture(autouse=True)
def isolate_cognition_stores(tmp_path_factory, monkeypatch):
    """Keep mind ledgers and shared episodes out of the repository's data/."""
    root = tmp_path_factory.mktemp("cognition")
    monkeypatch.setenv("FRIDAY_MIND_DIR", str(root / "minds"))
    monkeypatch.setenv("FRIDAY_EPISODE_LOG", str(root / "episodes.jsonl"))
    monkeypatch.setenv("FRIDAY_AUTONOMY_LEDGER", str(root / "autonomy_mandates.json"))
    monkeypatch.setenv("FRIDAY_SELF_REPAIR_STATE", str(root / "self_repair_state.json"))
    # The process-wide singletons must be rebuilt, or they keep the previous
    # test's directory for the rest of the session.
    import friday.cognition.memory_bridge as memory_bridge
    import friday.cognition.mind as mind_module

    monkeypatch.setattr(memory_bridge, "_SHARED", None)
    monkeypatch.setattr(mind_module, "_REGISTRY", None)
    yield


@pytest.fixture()
def approve_directives(monkeypatch):
    """Let a test exercise desktop-directive mechanics without an agent.

    ``WindowsFridayController.handle_directive`` now requires an authorizer for
    anything with real-world effect (composing mail, sending a WhatsApp
    message). Production callers - the agent fast path, the HTTP API, the CLI
    and the voice session - all pass their agent's authorizer, and a caller that
    passes none is refused.

    Directive tests are about parsing, receipts and message wording, not about
    who is allowed to act, so they opt in here and receive an authorizer that
    approves. The refusal path is pinned separately in
    ``test_workspace_policy_and_directive_authorization.py``; this fixture
    deliberately does not touch a call that supplies its own authorizer, so a
    test can still assert a denial.
    """
    from friday.core.types import (
        AuthorizationDecision,
        AuthorizationResponse,
    )
    from friday.devices import windows_friday as wf

    class _Approving:
        def authorize(self, request):
            return AuthorizationResponse(
                decision=AuthorizationDecision.APPROVED,
                reason="test fixture: approved",
            )

    original = wf.WindowsFridayController.handle_directive
    approver = _Approving()

    def patched(self, command, authorizer=None):
        return original(self, command, authorizer=authorizer or approver)

    monkeypatch.setattr(wf.WindowsFridayController, "handle_directive", patched)
    yield approver
