"""Configuration management for FRIDAY using Pydantic Settings."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type
from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def find_project_root() -> Path:
    """Dynamically resolve the project root directory by searching for workspace markers."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file() or (parent / ".git").exists():
            return parent
    return Path.cwd().resolve()


def resolve_env_file() -> Path:
    """Find the project .env file if it exists, checking multiple safe candidate locations."""
    # 1. Explicit environment variable override
    env_override = os.environ.get("FRIDAY_ENV_FILE")
    if env_override:
        p = Path(env_override).resolve()
        if p.is_file():
            return p

    # 2. Project root .env
    root = find_project_root()
    root_env = root / ".env"
    if root_env.is_file():
        return root_env.resolve()

    # 3. Current working directory .env
    cwd_env = Path.cwd().resolve() / ".env"
    if cwd_env.is_file():
        return cwd_env.resolve()

    # 4. Fallback path in project root
    return (root / ".env").resolve()


class NonEmptyEnvSettingsSource(EnvSettingsSource):
    """Environment settings source that ignores empty-string environment variables."""

    def get_field_value(self, field: Any, field_name: str) -> Tuple[Any, str, bool]:
        val, val_name, is_complex = super().get_field_value(field, field_name)
        if isinstance(val, str) and val.strip() == "":
            return None, val_name, is_complex
        return val, val_name, is_complex


class Settings(BaseSettings):
    """Central configuration for FRIDAY application."""

    model_config = SettingsConfigDict(
        env_file=str(resolve_env_file()),
        env_file_encoding="utf-8",
        env_prefix="FRIDAY_",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            NonEmptyEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # General
    env: str = Field(default="development", description="Environment (development, production, testing)")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    log_file: Optional[str] = Field(default="logs/friday.log", description="Path to log file")

    # LLM Settings & Cost Controls
    llm_provider: str = Field(default="gemini", description="LLM provider name: 'mock', 'openai', 'gemini'")
    llm_model: str = Field(default="gemini-2.5-flash", description="Model identifier")
    llm_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_LLM_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY", "llm_api_key"),
        description="API Key for the provider (OpenAI or general)",
    )
    gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key"),
        description="API Key specifically for Google Gemini",
    )
    gemini_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_MODEL", "GEMINI_MODEL", "gemini_model"),
        description="Optional Gemini-specific model name override",
    )
    gemini_timeout: float = Field(default=60.0, ge=1.0, le=600.0, description="Request timeout in seconds for Gemini API")
    gemini_max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts for transient Gemini API errors")
    gemini_backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0, description="Exponential backoff factor for retries")
    gemini_max_tokens: Optional[int] = Field(default=None, ge=1, le=32768, description="Max output tokens override for Gemini")
    gemini_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="Temperature override for Gemini")
    cost_mode: str = Field(default="free_first", description="Operating cost policy: 'free_first', 'custom'")
    max_daily_requests: Optional[int] = Field(default=None, ge=1, description="Optional safety limit on total daily LLM requests")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="Base URL for provider API")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768, description="Max tokens per response")

    # Memory & Semantic Settings
    memory_backend: str = Field(default="sqlite", description="Memory backend: 'sqlite', 'in_memory'")
    memory_db_path: str = Field(default="data/friday.db", description="Path to SQLite database file")
    memory_max_messages: int = Field(default=50, ge=2, description="Maximum messages stored in short-term buffer")
    memory_auto_persist: bool = Field(default=True, description="Whether to persist conversations automatically")
    memory_retention_days: Optional[int] = Field(default=None, ge=1, description="Optional retention policy in days (older messages pruned)")
    embedding_provider: str = Field(default="gemini", description="Embedding provider: 'gemini', 'mock', 'none'")
    embedding_model: str = Field(default="gemini-embedding-2", description="Embedding model identifier")
    embedding_dimension: int = Field(default=768, ge=1, le=8192, description="Expected dimensionality of embedding vectors")
    embedding_similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum cosine similarity threshold for semantic retrieval")
    retrieval_mode: str = Field(default="hybrid", description="Memory recall mode: 'hybrid', 'semantic', 'fts', 'none'")
    max_recalled_memories: int = Field(default=3, ge=1, le=20, description="Maximum historical memories to recall into context")
    recall_similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum similarity threshold for recalled memories")
    max_recall_chars: int = Field(default=1000, ge=100, le=10000, description="Maximum total characters of recalled memories injected")
    enable_auto_recall: bool = Field(default=True, description="Whether to automatically retrieve relevant historical context")

    # Identity
    agent_name: str = Field(default="FRIDAY", description="Name of the AI assistant")
    user_name: str = Field(default="Surendra", description="Name/title to address the user")
    # Backup configuration
    backup_dir: str = Field(default="data/backups", description="Directory for SQLite hot backups")

    # Voice Interface Settings
    voice_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("FRIDAY_VOICE_ENABLED", "VOICE_ENABLED", "voice_enabled"),
        description="Enable voice interface",
    )
    voice_provider: str = Field(default="gemini", description="Voice provider: 'gemini' or 'mock'")
    voice_input_sample_rate: int = Field(default=16000, description="Audio sample rate for microphone input (Hz)")
    voice_output_format: str = Field(default="mp3", description="Audio format for synthesized speech")
    voice_playback_buffer_ms: int = Field(default=100, description="Playback buffer size in milliseconds for non‑blocking audio")
    voice_live_model: str = Field(
        default="gemini-2.5-flash-native-audio-latest",
        validation_alias=AliasChoices("FRIDAY_VOICE_LIVE_MODEL", "VOICE_LIVE_MODEL", "voice_live_model"),
        description="Gemini Live multimodal voice model",
    )
    voice_live_sample_rate: int = Field(default=24000, description="Audio sample rate for Gemini Live output (Hz)")
    voice_live_output_format: str = Field(default="pcm", description="Audio format returned by Gemini Live (raw PCM)")
    voice_live_max_retries: int = Field(default=3, description="Max retries for live‑stream failures")
    task_enabled: bool = Field(default=False, description="Enable proactive task automation")
    task_max_calls: int = Field(default=100, description="Maximum allowed LLM calls per task")
    task_retry_limit: int = Field(default=3, description="Maximum retry attempts for transient failures")
    task_daily_cap: Optional[int] = Field(default=None, description="Optional cap on total daily task executions")
    task_circuit_breaker_threshold: int = Field(default=5, description="Consecutive failure count before disabling a task")

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return non-sensitive configuration diagnostics without exposing secrets."""
        has_gemini_key = bool(self.gemini_api_key and self.gemini_api_key.strip())
        has_general_key = bool(self.llm_api_key and self.llm_api_key.strip())
        return {
            "env": self.env,
            "provider": self.llm_provider,
            "model": self.gemini_model or self.llm_model,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "voice_enabled": self.voice_enabled,
            "voice_provider": self.voice_provider,
            "cost_mode": self.cost_mode,
            "gemini_key_present": has_gemini_key or has_general_key,
            "user_name": self.user_name,
        }

    def __repr__(self) -> str:
        """Safe string representation masking sensitive secrets."""
        masked_key = "***" if self.llm_api_key else None
        masked_gemini_key = "***" if self.gemini_api_key else None
        return (
            f"Settings(env={self.env!r}, log_level={self.log_level!r}, "
            f"llm_provider={self.llm_provider!r}, llm_model={self.llm_model!r}, "
            f"cost_mode={self.cost_mode!r}, "
            f"llm_api_key={masked_key!r}, gemini_api_key={masked_gemini_key!r}, "
            f"memory_max_messages={self.memory_max_messages})"
        )


@lru_cache(maxsize=1)
def _get_cached_settings() -> Settings:
    return Settings()


def get_settings(reload: bool = False) -> Settings:
    """Retrieve global settings instance with optional cache reload."""
    if reload:
        _get_cached_settings.cache_clear()
    return _get_cached_settings()
