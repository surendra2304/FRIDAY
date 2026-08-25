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
    # UI Automation flag – enabled by default on Windows, disabled otherwise
    ui_automation_enabled: bool = Field(
        default=bool(os.name == "nt"),
        description="Enable Windows UI Automation provider (default true on Windows).",
    )
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    log_file: Optional[str] = Field(default="logs/friday.log", description="Path to log file")

    # LLM Settings & Cost Controls
    llm_provider: str = Field(default="gemini", description="LLM provider name: 'mock', 'openai', 'gemini'")
    llm_model: str = Field(default="gemini-1.5-flash-latest", description="Model identifier")
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
    gemini_fallback_api_key_1: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_FALLBACK_API_KEY_1", "GEMINI_FALLBACK_API_KEY_1"),
        description="Fallback Gemini API Key 1",
    )
    gemini_fallback_api_key_2: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_FALLBACK_API_KEY_2", "GEMINI_FALLBACK_API_KEY_2"),
        description="Fallback Gemini API Key 2",
    )
    gemini_fallback_api_key_3: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_FALLBACK_API_KEY_3", "GEMINI_FALLBACK_API_KEY_3"),
        description="Fallback Gemini API Key 3",
    )
    gemini_fallback_api_key_4: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GEMINI_FALLBACK_API_KEY_4", "GEMINI_FALLBACK_API_KEY_4"),
        description="Fallback Gemini API Key 4",
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
    llm_thinking_level: str = Field(
        default="medium",
        validation_alias=AliasChoices("FRIDAY_LLM_THINKING_LEVEL", "LLM_THINKING_LEVEL", "llm_thinking_level"),
        description="Thinking level for Gemini 3.7 Flash: low, medium, high"
    )
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768, description="Max tokens per response")

    # Groq (text/reasoning provider; OpenAI-SDK compatible)
    groq_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GROQ_API_KEY", "GROQ_API_KEY", "groq_api_key"),
        description="API Key for Groq (text/reasoning only; never used for voice)",
    )
    groq_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GROQ_MODEL", "GROQ_MODEL", "groq_model"),
        description="Optional Groq model override (default: llama-3.3-70b-versatile)",
    )
    groq_fallback_model: str = Field(
        default="openai/gpt-oss-20b",
        validation_alias=AliasChoices("FRIDAY_GROQ_FALLBACK_MODEL", "GROQ_FALLBACK_MODEL", "groq_fallback_model"),
        description="Groq fallback model used on 429 rate limits",
    )

    # OpenRouter (text/reasoning provider; OpenAI-SDK compatible)
    openrouter_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY", "openrouter_api_key"),
        description="API Key for OpenRouter (text/reasoning only; never used for voice)",
    )
    openrouter_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_OPENROUTER_MODEL", "OPENROUTER_MODEL", "openrouter_model"),
        description="Optional OpenRouter model override (default: meta-llama/llama-3.3-70b-instruct)",
    )

    # Cerebras (text/reasoning provider; OpenAI-SDK compatible)
    cerebras_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_CEREBRAS_API_KEY", "CEREBRAS_API_KEY", "cerebras_api_key"),
        description="API Key for Cerebras (text/reasoning only; never used for voice)",
    )
    cerebras_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_CEREBRAS_MODEL", "CEREBRAS_MODEL", "cerebras_model"),
        description="Optional Cerebras model override (default: llama3.1-8b-8192)",
    )

    # Mistral (deep-fallback text/reasoning provider; OpenAI-SDK compatible)
    mistral_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_MISTRAL_API_KEY", "MISTRAL_API_KEY", "mistral_api_key"),
        description="API Key for Mistral (text/reasoning only; never used for voice)",
    )
    mistral_model: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_MISTRAL_MODEL", "MISTRAL_MODEL", "mistral_model"),
        description="Optional Mistral model override (default: mistral-large-latest)",
    )

    # GitHub Integration
    github_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_GITHUB_TOKEN", "GITHUB_TOKEN", "github_token"),
        description="Personal Access Token for GitHub Automation",
    )

    # IoT & Smart Home Hub Settings (Phase 27)
    iot_hub_url: str = Field(
        default="http://localhost:8123",
        validation_alias=AliasChoices("FRIDAY_IOT_HUB_URL", "IOT_HUB_URL", "iot_hub_url"),
        description="Base URL for local Smart Home / IoT Hub (e.g. Home Assistant or local bridge)",
    )
    iot_hub_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_IOT_HUB_TOKEN", "IOT_HUB_TOKEN", "iot_hub_token"),
        description="Bearer token or API key for local Smart Home / IoT Hub",
    )

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
    audio_input_device: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_AUDIO_INPUT_DEVICE", "AUDIO_INPUT_DEVICE", "audio_input_device"),
        description="Optional name or index of specific audio input device (microphone)",
    )
    audio_output_device: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FRIDAY_AUDIO_OUTPUT_DEVICE", "AUDIO_OUTPUT_DEVICE", "audio_output_device"),
        description="Optional name or index of specific audio output device (speaker)",
    )
    voice_input_sample_rate: int = Field(default=16000, description="Audio sample rate for microphone input (Hz)")
    voice_output_format: str = Field(default="mp3", description="Audio format for synthesized speech")
    voice_name: str = Field(
        default="Aoede",
        validation_alias=AliasChoices("FRIDAY_VOICE_NAME", "VOICE_NAME", "voice_name"),
        description="Prebuilt voice name for Gemini speech synthesis (e.g. Aoede, Puck, Charon, Kore, Fenrir)",
    )
    voice_playback_buffer_ms: int = Field(default=100, description="Playback buffer size in milliseconds for non‑blocking audio")
    voice_live_model: str = Field(
        default="gemini-3.1-flash-live-preview",
        validation_alias=AliasChoices("FRIDAY_VOICE_LIVE_MODEL", "VOICE_LIVE_MODEL", "voice_live_model"),
        description="Gemini Live multimodal voice model",
    )
    voice_live_sample_rate: int = Field(default=24000, description="Audio sample rate for Gemini Live output (Hz)")
    voice_live_max_retries: int = Field(default=3, description="Max retries for live‑stream failures")
    voice_live_reconnect_delay: float = Field(default=1.0, ge=0.1, le=30.0, description="Initial reconnect delay in seconds")
    voice_session_resumption_enabled: bool = Field(default=True, description="Enable Gemini Live session resumption")
    voice_context_compression_enabled: bool = Field(default=True, description="Enable Gemini Live context window compression")
    voice_vad_start_sensitivity: str = Field(
        default="LOW",
        validation_alias=AliasChoices("FRIDAY_VOICE_VAD_START_SENSITIVITY", "VOICE_VAD_START_SENSITIVITY", "voice_vad_start_sensitivity"),
        description="VAD start of speech sensitivity: HIGH, LOW, UNSPECIFIED (LOW prevents premature false turn starts on breath/ambient noise)",
    )
    voice_vad_end_sensitivity: str = Field(
        default="HIGH",
        validation_alias=AliasChoices("FRIDAY_VOICE_VAD_END_SENSITIVITY", "VOICE_VAD_END_SENSITIVITY", "voice_vad_end_sensitivity"),
        description="VAD end of speech sensitivity: HIGH, LOW, UNSPECIFIED",
    )
    voice_vad_prefix_padding_ms: int = Field(default=300, ge=0, le=1000, description="VAD prefix audio padding (ms)")
    voice_vad_silence_duration_ms: int = Field(default=800, ge=100, le=2000, description="VAD silence duration before turn complete (ms)")
    voice_speaker_timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=60000,
        validation_alias=AliasChoices("FRIDAY_VOICE_SPEAKER_TIMEOUT_MS", "VOICE_SPEAKER_TIMEOUT_MS", "voice_speaker_timeout_ms", "speaker_timeout_ms"),
        description="Maximum continuous speaker playback timeout before auto-unmuting mic (1000ms to 60000ms)",
    )
    voice_barge_in_rms_threshold: float = Field(default=350.0, ge=50.0, le=5000.0, description="RMS energy threshold for local zero-latency barge-in")
    voice_barge_in_consecutive_frames: int = Field(default=4, ge=1, le=20, description="Consecutive frames exceeding threshold required to confirm user barge-in (debounce)")
    voice_barge_in_playback_factor: float = Field(default=3.0, ge=1.0, le=20.0, description="Multiplier for barge-in threshold when FRIDAY is actively playing audio (echo protection)")
    voice_barge_in_cooldown_seconds: float = Field(default=1.0, ge=0.0, le=5.0, description="Cooldown window after an interruption during which new local interruptions are suppressed")
    voice_local_barge_in_during_playback: bool = Field(
        default=False,
        validation_alias=AliasChoices("FRIDAY_VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK", "VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK", "voice_local_barge_in_during_playback"),
        description="Whether to allow local RMS detector to interrupt during speaker playback (False lets Gemini Server VAD drive authoritative interruptions to prevent acoustic echo self-interruption)",
    )
    voice_headphones_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("FRIDAY_VOICE_HEADPHONES_MODE", "VOICE_HEADPHONES_MODE", "voice_headphones_mode"),
        description="Whether headphones are used (enables local barge-in during playback with lower threshold)",
    )
    voice_biometrics_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("FRIDAY_VOICE_BIOMETRICS_ENABLED", "VOICE_BIOMETRICS_ENABLED", "voice_biometrics_enabled"),
        description="Enroll and verify the owner's voice before obeying spoken commands (resemblyzer; enroll with 'friday --enroll-voice')",
    )
    voice_adaptive_noise_alpha: float = Field(default=0.05, ge=0.001, le=0.5, description="Exponential moving average alpha for tracking ambient noise floor")
    voice_adaptive_noise_multiplier: float = Field(default=3.5, ge=1.5, le=10.0, description="Adaptive noise floor multiplier to declare candidate speech")
    voice_thinking_level: str = Field(
        default="MINIMAL",
        validation_alias=AliasChoices("FRIDAY_VOICE_THINKING_LEVEL", "VOICE_THINKING_LEVEL", "voice_thinking_level"),
        description="Thinking level for Gemini 3.1 Live session: MINIMAL, LOW, MEDIUM, HIGH",
    )
    voice_thinking_budget: Optional[int] = Field(default=0, ge=0, le=2048, description="Deprecated: Thinking budget tokens for legacy models")
    
    # Vision & Multimodal Settings
    vision_model: str = Field(
        default="gemini-3.6-flash",
        validation_alias=AliasChoices("FRIDAY_VISION_MODEL", "VISION_MODEL", "vision_model"),
        description="Multimodal Gemini vision model identifier",
    )
    vision_provider: str = Field(
        default="gemini",
        validation_alias=AliasChoices("FRIDAY_VISION_PROVIDER", "VISION_PROVIDER", "vision_provider"),
        description="Vision provider: 'gemini' or 'mock'",
    )
    vision_max_image_bytes: int = Field(
        default=20971520,  # 20 MB
        description="Maximum allowed image size in bytes for visual analysis",
    )
    screen_capture_provider: str = Field(
        default="windows",
        validation_alias=AliasChoices("FRIDAY_SCREEN_CAPTURE_PROVIDER", "SCREEN_CAPTURE_PROVIDER", "screen_capture_provider"),
        description="Screen capture provider backend: 'windows' or 'mock'",
    )
    screen_display: str = Field(
        default="primary",
        validation_alias=AliasChoices("FRIDAY_SCREEN_DISPLAY", "SCREEN_DISPLAY", "screen_display"),
        description="Target display for capture: 'primary' or display index '0', '1', etc.",
    )
    screen_capture_timeout: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="Maximum timeout in seconds for screen capture operation",
    )
    screen_aware: bool = Field(
        default=False,
        validation_alias=AliasChoices("FRIDAY_SCREEN_AWARE", "SCREEN_AWARE", "screen_aware"),
        description="Whether background periodic screen awareness is enabled (default False)",
    )
    screen_interval_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=3600.0,
        validation_alias=AliasChoices("FRIDAY_SCREEN_INTERVAL_SECONDS", "SCREEN_INTERVAL_SECONDS", "screen_interval_seconds"),
        description="Minimum interval in seconds between periodic screen captures",
    )
    screen_change_threshold: float = Field(
        default=0.05,
        ge=0.001,
        le=1.0,
        validation_alias=AliasChoices("FRIDAY_SCREEN_CHANGE_THRESHOLD", "SCREEN_CHANGE_THRESHOLD", "screen_change_threshold"),
        description="Minimum image difference ratio (0.0 to 1.0) required to trigger visual analysis for changed screens",
    )

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
