"""Configuration management for FRIDAY using Pydantic Settings."""

from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for FRIDAY application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FRIDAY_",
        extra="ignore",
    )

    # General
    env: str = Field(default="development", description="Environment (development, production, testing)")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    log_file: Optional[str] = Field(default="logs/friday.log", description="Path to log file")

    # LLM Settings
    llm_provider: str = Field(default="mock", description="LLM provider name: 'mock', 'openai', 'gemini'")
    llm_model: str = Field(default="gemini-2.5-flash", description="Model identifier")
    llm_api_key: Optional[str] = Field(default=None, description="API Key for the provider (OpenAI or general)")
    gemini_api_key: Optional[str] = Field(default=None, description="API Key specifically for Google Gemini")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="Base URL for provider API")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768, description="Max tokens per response")

    # Memory Settings
    memory_backend: str = Field(default="sqlite", description="Memory backend: 'sqlite', 'in_memory'")
    memory_db_path: str = Field(default="data/friday.db", description="Path to SQLite database file")
    memory_max_messages: int = Field(default=50, ge=2, description="Maximum messages stored in short-term buffer")
    memory_auto_persist: bool = Field(default=True, description="Whether to persist conversations automatically")
    memory_retention_days: Optional[int] = Field(default=None, ge=1, description="Optional retention policy in days (older messages pruned)")

    # Identity
    agent_name: str = Field(default="FRIDAY", description="Name of the AI assistant")
    user_name: str = Field(default="Boss", description="Name/title to address the user")

    def __repr__(self) -> str:
        """Safe string representation masking sensitive secrets."""
        masked_key = "***" if self.llm_api_key else None
        masked_gemini_key = "***" if self.gemini_api_key else None
        return (
            f"Settings(env={self.env!r}, log_level={self.log_level!r}, "
            f"llm_provider={self.llm_provider!r}, llm_model={self.llm_model!r}, "
            f"llm_api_key={masked_key!r}, gemini_api_key={masked_gemini_key!r}, "
            f"memory_max_messages={self.memory_max_messages})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve cached global settings instance."""
    return Settings()
