"""Tests for configuration system and secret masking."""

import os
from unittest import mock
from friday.core.config import Settings, get_settings


def test_default_settings():
    settings = Settings()
    assert settings.env == "development"
    assert settings.llm_provider == "mock"
    assert settings.memory_max_messages == 50
    assert settings.agent_name == "FRIDAY"


def test_settings_custom_values():
    settings = Settings(
        env="production",
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_api_key="sk-secret-1234567890",
        memory_max_messages=100,
    )
    assert settings.env == "production"
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-4o"
    assert settings.llm_api_key == "sk-secret-1234567890"
    assert settings.memory_max_messages == 100


def test_settings_secret_masking():
    settings = Settings(
        llm_api_key="sk-super-secret-key-12345",
    )
    repr_str = repr(settings)
    assert "sk-super-secret-key-12345" not in repr_str
    assert "***" in repr_str


def test_env_var_override():
    with mock.patch.dict(os.environ, {"FRIDAY_LLM_PROVIDER": "openai", "FRIDAY_USER_NAME": "Commander"}):
        settings = Settings()
        assert settings.llm_provider == "openai"
        assert settings.user_name == "Commander"
