"""Tests for configuration system and secret masking."""

import os
from unittest import mock
from friday.core.config import Settings, get_settings


def test_default_settings():
    settings = Settings()
    assert settings.env == "development"
    assert settings.llm_provider == "gemini"
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


def test_dotenv_file_loading_overrides_defaults(tmp_path):
    """Test A: .env values override code defaults."""
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "FRIDAY_LLM_PROVIDER=openai\n"
        "FRIDAY_GEMINI_MODEL=gemini-3.6-flash\n"
        "FRIDAY_EMBEDDING_PROVIDER=mock\n"
        "FRIDAY_VOICE_ENABLED=true\n"
        "FRIDAY_USER_NAME=Alex\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=str(env_file))
    assert settings.llm_provider == "openai"
    assert settings.gemini_model == "gemini-3.6-flash"
    assert settings.embedding_provider == "mock"
    assert settings.voice_enabled is True
    assert settings.user_name == "Alex"


def test_process_env_overrides_dotenv(tmp_path):
    """Test B: Explicit process environment variables override .env values."""
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "FRIDAY_LLM_PROVIDER=gemini\n"
        "FRIDAY_USER_NAME=FromDotEnv\n",
        encoding="utf-8",
    )
    with mock.patch.dict(os.environ, {"FRIDAY_USER_NAME": "FromProcessEnv"}):
        settings = Settings(_env_file=str(env_file))
        assert settings.llm_provider == "gemini"
        assert settings.user_name == "FromProcessEnv"


def test_empty_process_env_does_not_wipe_dotenv_value(tmp_path):
    """Verify that an empty process environment variable does not erase .env value."""
    env_file = tmp_path / "custom.env"
    env_file.write_text(
        "FRIDAY_GEMINI_MODEL=gemini-3.6-flash\n"
        "FRIDAY_USER_NAME=Surendra\n",
        encoding="utf-8",
    )
    with mock.patch.dict(os.environ, {"FRIDAY_GEMINI_MODEL": ""}):
        settings = Settings(_env_file=str(env_file))
        assert settings.gemini_model == "gemini-3.6-flash"
        assert settings.user_name == "Surendra"


def test_missing_dotenv_falls_back_to_defaults(tmp_path):
    """Test C: Missing .env file falls back to code defaults."""
    non_existent = tmp_path / "non_existent.env"
    settings = Settings(_env_file=str(non_existent))
    assert settings.llm_provider == "gemini"
    assert settings.embedding_provider == "gemini"
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.voice_enabled is False


def test_gemini_key_detected_without_leakage(tmp_path):
    """Test D: Gemini key presence is detected in diagnostics without exposing raw value."""
    env_file = tmp_path / "secret.env"
    env_file.write_text("FRIDAY_GEMINI_API_KEY=TEST_GEMINI_API_KEY_PLACEHOLDER_17SecretTestKey12345\n", encoding="utf-8")
    settings = Settings(_env_file=str(env_file))

    diagnostics = settings.get_diagnostics()
    assert diagnostics["gemini_key_present"] is True
    # Ensure raw secret string is not in diagnostic keys or values
    diag_str = str(diagnostics)
    assert "TEST_GEMINI_API_KEY_PLACEHOLDER_17SecretTestKey12345" not in diag_str
    assert "TEST_GEMINI_API_KEY_PLACEHOLDER_17SecretTestKey12345" not in repr(settings)


def test_voice_enabled_true_respected(tmp_path):
    """Test E: voice_enabled=true in .env is correctly respected."""
    env_file = tmp_path / "voice_on.env"
    env_file.write_text("FRIDAY_VOICE_ENABLED=true\n", encoding="utf-8")
    settings = Settings(_env_file=str(env_file))
    assert settings.voice_enabled is True
    assert settings.get_diagnostics()["voice_enabled"] is True


def test_voice_enabled_false_respected(tmp_path):
    """Test F: voice_enabled=false in .env is correctly respected."""
    env_file = tmp_path / "voice_off.env"
    env_file.write_text("FRIDAY_VOICE_ENABLED=false\n", encoding="utf-8")
    settings = Settings(_env_file=str(env_file))
    assert settings.voice_enabled is False
    assert settings.get_diagnostics()["voice_enabled"] is False
