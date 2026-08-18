"""Pytest fixtures for FRIDAY test suite."""

import sys
from pathlib import Path
import pytest

# Ensure src/ is on Python search path
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from friday.core.config import Settings
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


@pytest.fixture
def mock_settings() -> Settings:
    """Fixture providing clean default settings for testing."""
    return Settings(
        env="testing",
        log_level="DEBUG",
        log_file=None,
        llm_provider="mock",
        llm_model="mock-gpt",
        llm_api_key="sk-test-secret-key-1234567890",
        memory_max_messages=10,
        agent_name="FRIDAY-TEST",
        user_name="Boss",
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
