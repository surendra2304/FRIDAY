import sys
from pathlib import Path
import pytest

try:
    import pandas  # Initialize pandas C-extensions before test monkeypatching
except Exception:
    pass

# Ensure src/ is on Python search path
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry
from friday.auth.request_accounting import RequestAccountant, BudgetLimits, request_accountant
from friday.auth.credential_pool import credential_pool
import os
from unittest.mock import patch


@pytest.fixture(autouse=True)
def reset_accounting_and_pool_state():
    """Ensure clean accounting and credential pool state for every single test."""
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
