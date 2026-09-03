"""Configuration management for FRIDAY using Pydantic Settings."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
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



    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
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

    def __init__(self, **kwargs):
        import os
        import warnings
        
        legacy_aliases = {'FRIDAY_IOT_HUB_URL': ['IOT_HUB_URL', 'iot_hub_url'], 'FRIDAY_IOT_HUB_TOKEN': ['IOT_HUB_TOKEN', 'iot_hub_token'], 'FRIDAY_CALENDAR_ICS_URL': ['CALENDAR_ICS_URL', 'calendar_ics_url'], 'FRIDAY_EMAIL_ADDRESS': ['EMAIL_ADDRESS', 'email_address'], 'FRIDAY_EMAIL_APP_PASSWORD': ['EMAIL_APP_PASSWORD', 'email_app_password'], 'FRIDAY_EMAIL_SMTP_HOST': ['EMAIL_SMTP_HOST', 'email_smtp_host'], 'FRIDAY_EMAIL_SMTP_PORT': ['EMAIL_SMTP_PORT', 'email_smtp_port'], 'FRIDAY_ACTIVE_DEVICE': ['ACTIVE_DEVICE', 'active_device'], 'FRIDAY_UNIVERSE_API_URL': ['AI_UNIVERSE_API_URL', 'FRIDAY_AI_UNIVERSE_API_URL', 'universe_api_url'], 'FRIDAY_VOICE_ENABLED': ['VOICE_ENABLED', 'voice_enabled'], 'FRIDAY_AUDIO_INPUT_DEVICE': ['AUDIO_INPUT_DEVICE', 'audio_input_device'], 'FRIDAY_AUDIO_OUTPUT_DEVICE': ['AUDIO_OUTPUT_DEVICE', 'audio_output_device'], 'FRIDAY_VOICE_NAME': ['VOICE_NAME', 'voice_name'], 'FRIDAY_VOICE_LIVE_MODEL': ['VOICE_LIVE_MODEL', 'voice_live_model'], 'FRIDAY_VOICE_VAD_START_SENSITIVITY': ['VOICE_VAD_START_SENSITIVITY', 'voice_vad_start_sensitivity'], 'FRIDAY_VOICE_VAD_END_SENSITIVITY': ['VOICE_VAD_END_SENSITIVITY', 'voice_vad_end_sensitivity'], 'FRIDAY_VOICE_SPEAKER_TIMEOUT_MS': ['VOICE_SPEAKER_TIMEOUT_MS', 'voice_speaker_timeout_ms', 'speaker_timeout_ms'], 'FRIDAY_VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK': ['VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK', 'voice_local_barge_in_during_playback'], 'FRIDAY_VOICE_HEADPHONES_MODE': ['VOICE_HEADPHONES_MODE', 'voice_headphones_mode'], 'FRIDAY_VOICE_BIOMETRICS_ENABLED': ['VOICE_BIOMETRICS_ENABLED', 'voice_biometrics_enabled'], 'FRIDAY_VOICE_THINKING_LEVEL': ['VOICE_THINKING_LEVEL', 'voice_thinking_level'], 'FRIDAY_VISION_MODEL': ['VISION_MODEL', 'vision_model'], 'FRIDAY_VISION_PROVIDER': ['VISION_PROVIDER', 'vision_provider'], 'FRIDAY_SCREEN_CAPTURE_PROVIDER': ['SCREEN_CAPTURE_PROVIDER', 'screen_capture_provider'], 'FRIDAY_SCREEN_DISPLAY': ['SCREEN_DISPLAY', 'screen_display'], 'FRIDAY_SCREEN_AWARE': ['SCREEN_AWARE', 'screen_aware'], 'FRIDAY_SCREEN_INTERVAL_SECONDS': ['SCREEN_INTERVAL_SECONDS', 'screen_interval_seconds'], 'FRIDAY_SCREEN_CHANGE_THRESHOLD': ['SCREEN_CHANGE_THRESHOLD', 'screen_change_threshold'], 'FRIDAY_PROACTIVE_WATCHER_ENABLED': ['PROACTIVE_WATCHER_ENABLED', 'proactive_watcher_enabled'], 'FRIDAY_WATCHER_INTERVAL_SECONDS': ['WATCHER_INTERVAL_SECONDS', 'watcher_interval_seconds'], 'FRIDAY_TESSERACT_CMD': ['TESSERACT_CMD', 'tesseract_cmd'], 'FRIDAY_FORGE_BASE_URL': ['FORGE_BASE_URL', 'FRIDAY_FORGE_API_URL', 'FORGE_API_URL', 'forge_api_url', 'forge_base_url'], 'FRIDAY_FORGE_API_KEY': ['FORGE_API_KEY', 'forge_api_key'], 'FRIDAY_FORGE_ENABLED': ['FORGE_ENABLED', 'forge_enabled'], 'FRIDAY_FORGE_MAX_CONCURRENT_TASKS': ['FORGE_MAX_CONCURRENT_TASKS', 'forge_max_concurrent_tasks'], 'FRIDAY_FORGE_TASK_TIMEOUT': ['FORGE_TASK_TIMEOUT', 'forge_task_timeout'], 'FRIDAY_FORGE_SUPERVISION_INTERVAL_SECONDS': ['FORGE_SUPERVISION_INTERVAL_SECONDS', 'forge_supervision_interval_seconds'], 'FRIDAY_FORGE_HEALTH_CHECK_INTERVAL_SECONDS': ['FORGE_HEALTH_CHECK_INTERVAL_SECONDS', 'forge_health_check_interval_seconds'], 'FRIDAY_ECOSYSTEM_ENABLED': ['ECOSYSTEM_ENABLED', 'ecosystem_enabled'], 'FRIDAY_TRADING_BOT_BASE_URL': ['STRATEX_URL', 'TRADING_BOT_BASE_URL', 'trading_bot_base_url'], 'FRIDAY_STRATEX_API_KEY': ['TRADING_BOT_API_KEY', 'BOT_API_KEY'], 'FRIDAY_AI_UNIVERSE_BASE_URL': ['INFERENCE_URL', 'AI_UNIVERSE_BASE_URL', 'ai_universe_base_url'], 'FRIDAY_INFERENCE_API_KEY': ['INFERENCE_API_KEY'], 'FRIDAY_INTELX_URL': ['INTELX_URL', 'intelx_base_url'], 'FRIDAY_FUTURIS_URL': ['FUTURIS_URL', 'futuris_base_url'], 'FRIDAY_MEMORA_URL': ['MEMORA_URL', 'memora_base_url'], 'FRIDAY_SENTINEL_URL': ['SENTINEL_URL', 'sentinel_base_url'], 'FRIDAY_NEXUS_BASE_URL': ['CORTEX_URL', 'NEXUS_URL', 'NEXUS_BASE_URL', 'nexus_base_url'], 'FRIDAY_NEXUS_ENABLED': ['NEXUS_ENABLED', 'CORTEX_ENABLED', 'nexus_enabled'], 'FRIDAY_NEXUS_VIGILANCE_INTERVAL_SECONDS': ['NEXUS_VIGILANCE_INTERVAL_SECONDS', 'nexus_vigilance_interval_seconds'], 'FRIDAY_LLM_API_KEY': ['OPENAI_API_KEY', 'LLM_API_KEY', 'llm_api_key'], 'FRIDAY_GEMINI_API_KEY': ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'gemini_api_key'], 'FRIDAY_GROQ_API_KEY': ['GROQ_API_KEY', 'groq_api_key'], 'FRIDAY_API_KEY': ['FRIDAY_UNIVERSE_API_KEY']}
        
        for canonical, aliases in legacy_aliases.items():
            if canonical not in os.environ:
                for alias in aliases:
                    if alias in os.environ:
                        warnings.warn(f"Environment variable '{alias}' is deprecated. Please use '{canonical}' instead.", DeprecationWarning, stacklevel=2)
                        kwargs[canonical[7:].lower()] = os.environ[alias]
                        break
        super().__init__(**kwargs)



    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
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
    log_file: str | None = Field(default="logs/friday.log", description="Path to log file")

    # LLM Settings & Cost Controls
    llm_provider: str = Field(default="gemini", description="LLM provider name: 'mock', 'openai', 'gemini'")
    llm_model: str = Field(default="gemini-1.5-flash-latest", description="Model identifier")
    llm_api_key: str | None = Field(
        default=None,
        description="API Key for the provider (OpenAI or general)",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="API Key specifically for Google Gemini",
    )
    gemini_fallback_api_key_1: str | None = Field(
        default=None,
        description="Fallback Gemini API Key 1",
    )
    gemini_fallback_api_key_2: str | None = Field(
        default=None,
        description="Fallback Gemini API Key 2",
    )
    gemini_fallback_api_key_3: str | None = Field(
        default=None,
        description="Fallback Gemini API Key 3",
    )
    gemini_fallback_api_key_4: str | None = Field(
        default=None,
        description="Fallback Gemini API Key 4",
    )
    gemini_model: str | None = Field(
        default=None,
        description="Optional Gemini-specific model name override",
    )
    gemini_timeout: float = Field(default=60.0, ge=1.0, le=600.0, description="Request timeout in seconds for Gemini API")
    gemini_max_retries: int = Field(default=3, ge=0, le=10, description="Max retry attempts for transient Gemini API errors")
    gemini_backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0, description="Exponential backoff factor for retries")
    gemini_max_tokens: int | None = Field(default=None, ge=1, le=32768, description="Max output tokens override for Gemini")
    gemini_temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="Temperature override for Gemini")
    cost_mode: str = Field(default="free_first", description="Operating cost policy: 'free_first', 'custom'")
    max_daily_requests: int | None = Field(default=None, ge=1, description="Optional safety limit on total daily LLM requests")
    llm_base_url: str = Field(default="https://api.openai.com/v1", description="Base URL for provider API")
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    llm_thinking_level: str = Field(
        default="medium",
        description="Thinking level for Gemini 3.7 Flash: low, medium, high"
    )
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768, description="Max tokens per response")

    # Groq (text/reasoning provider; OpenAI-SDK compatible)
    groq_api_key: str | None = Field(
        default=None,
        description="API Key for Groq (text/reasoning only; never used for voice)",
    )
    groq_model: str | None = Field(
        default=None,
        description="Optional Groq model override (default: openai/gpt-oss-120b)",
    )
    groq_fallback_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Groq fallback model used on 429 rate limits",
    )

    # OpenRouter (text/reasoning provider; OpenAI-SDK compatible)
    openrouter_api_key: str | None = Field(
        default=None,
        description="API Key for OpenRouter (text/reasoning only; never used for voice)",
    )
    openrouter_model: str | None = Field(
        default=None,
        description="Optional OpenRouter model override (default: meta-llama/llama-3.3-70b-instruct)",
    )

    # Mistral (deep-fallback text/reasoning provider; OpenAI-SDK compatible)
    mistral_api_key: str | None = Field(
        default=None,
        description="API Key for Mistral (text/reasoning only; never used for voice)",
    )
    mistral_model: str | None = Field(
        default=None,
        description="Optional Mistral model override (default: mistral-large-latest)",
    )

    # GitHub Integration
    github_token: str | None = Field(
        default=None,
        description="Personal Access Token for GitHub Automation",
    )

    # IoT & Smart Home Hub Settings (IoT & Smart Home Control)
    iot_hub_enabled: bool = Field(
        default=False,
        description="Whether local Smart Home / IoT Hub control is enabled",
    )
    iot_hub_url: str = Field(
        default="http://localhost:8123",
        description="Base URL for local Smart Home / IoT Hub (e.g. Home Assistant or local bridge)",
    )
    iot_hub_token: str | None = Field(
        default=None,
        description="Bearer token or API key for local Smart Home / IoT Hub",
    )

    # Calendar & Schedule Settings (Calendar & Morning Briefings)
    calendar_ics_url: str | None = Field(
        default=None,
        description="Public or secret read-only .ics URL for calendar integration",
    )

    # Email Integration Settings (Web Research & Email Automation)
    email_address: str | None = Field(
        default=None,
        description="User email address for outgoing SMTP mail (e.g. Gmail)",
    )
    email_app_password: str | None = Field(
        default=None,
        description="App Password / Token for outgoing SMTP mail",
    )
    email_smtp_host: str = Field(
        default="smtp.gmail.com",
        description="SMTP server hostname (default: smtp.gmail.com)",
    )
    email_smtp_port: int = Field(
        default=587,
        description="SMTP server port (default: 587 for STARTTLS)",
    )

    # Device Control Settings (OpenJarvis Device Control Abstraction)
    active_device: str = Field(
        default="windows",
        description="Active device controller target platform: 'windows', 'android', 'mock'",
    )

    # AI Universe Integration Settings (AI Universe Integration)
    universe_api_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for external AI Universe multi-agent debate API",
    )
    api_key: str | None = Field(
        default=None,
        description="API Key for authenticating FRIDAY with external AI Universe services",
    )

    # Face Biometrics Authentication Settings
    face_auth_enabled: bool = Field(
        default=False,
        description="Whether facial recognition biometric authentication is enabled",
    )
    face_similarity_threshold: float = Field(
        default=0.70,
        description="Cosine similarity threshold for face recognition verification",
    )
    face_profile_dir: str = Field(
        default="data/face_profiles",
        description="Directory storing enrolled face profiles",
    )

    # Desktop Companion Shell Settings
    desktop_enabled: bool = Field(
        default=True,
        description="Whether the floating desktop companion overlay is enabled",
    )
    desktop_hotkey: str = Field(
        default="Ctrl+Shift+Space",
        description="Global Windows hotkey to summon or toggle the FRIDAY desktop companion",
    )

    # Microsoft JARVIS / HuggingGPT Planning Engine Settings
    planner_enabled: bool = Field(
        default=True,
        description="Whether dynamic task graph decomposition and multi-model planning is enabled",
    )
    planner_max_concurrent_tasks: int = Field(
        default=5,
        ge=1,
        description="Maximum concurrent subtasks executed in parallel",
    )
    planner_task_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Default timeout per subtask in seconds",
    )
    planner_max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retries per subtask on transient failures",
    )
    planner_model: str | None = Field(
        default=None,
        description="Optional model identifier override dedicated to task decomposition",
    )

    # Memory & Semantic Settings
    memory_backend: str = Field(default="sqlite", description="Memory backend: 'sqlite', 'in_memory'")
    memory_db_path: str = Field(default="data/friday.db", description="Path to SQLite database file")
    memory_max_messages: int = Field(default=50, ge=2, description="Maximum messages stored in short-term buffer")
    memory_auto_persist: bool = Field(default=True, description="Whether to persist conversations automatically")
    memory_retention_days: int | None = Field(default=None, ge=1, description="Optional retention policy in days (older messages pruned)")
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
        description="Enable voice interface",
    )
    voice_provider: str = Field(default="gemini", description="Voice provider: 'gemini' or 'mock'")
    audio_input_device: str | None = Field(
        default=None,
        description="Optional name or index of specific audio input device (microphone)",
    )
    audio_output_device: str | None = Field(
        default=None,
        description="Optional name or index of specific audio output device (speaker)",
    )
    voice_input_sample_rate: int = Field(default=16000, description="Audio sample rate for microphone input (Hz)")
    voice_output_format: str = Field(default="mp3", description="Audio format for synthesized speech")
    voice_name: str = Field(
        default="Aoede",
        description="Prebuilt voice name for Gemini speech synthesis (e.g. Aoede, Puck, Charon, Kore, Fenrir)",
    )
    voice_playback_buffer_ms: int = Field(default=100, description="Playback buffer size in milliseconds for non‑blocking audio")
    voice_live_model: str = Field(
        default="gemini-3.1-flash-live-preview",
        description="Gemini Live multimodal voice model",
    )
    voice_live_sample_rate: int = Field(default=24000, description="Audio sample rate for Gemini Live output (Hz)")
    voice_live_max_retries: int = Field(default=3, description="Max retries for live‑stream failures")
    voice_live_reconnect_delay: float = Field(default=1.0, ge=0.1, le=30.0, description="Initial reconnect delay in seconds")
    voice_session_resumption_enabled: bool = Field(default=True, description="Enable Gemini Live session resumption")
    voice_context_compression_enabled: bool = Field(default=True, description="Enable Gemini Live context window compression")
    voice_vad_start_sensitivity: str = Field(
        default="LOW",
        description="VAD start of speech sensitivity: HIGH, LOW, UNSPECIFIED (LOW prevents premature false turn starts on breath/ambient noise)",
    )
    voice_vad_end_sensitivity: str = Field(
        default="HIGH",
        description="VAD end of speech sensitivity: HIGH, LOW, UNSPECIFIED",
    )
    voice_vad_prefix_padding_ms: int = Field(default=300, ge=0, le=1000, description="VAD prefix audio padding (ms)")
    voice_vad_silence_duration_ms: int = Field(default=800, ge=100, le=2000, description="VAD silence duration before turn complete (ms)")
    voice_speaker_timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=60000,
        description="Maximum continuous speaker playback timeout before auto-unmuting mic (1000ms to 60000ms)",
    )
    voice_barge_in_rms_threshold: float = Field(default=350.0, ge=50.0, le=5000.0, description="RMS energy threshold for local zero-latency barge-in")
    voice_barge_in_consecutive_frames: int = Field(default=4, ge=1, le=20, description="Consecutive frames exceeding threshold required to confirm user barge-in (debounce)")
    voice_barge_in_playback_factor: float = Field(default=3.0, ge=1.0, le=20.0, description="Multiplier for barge-in threshold when FRIDAY is actively playing audio (echo protection)")
    voice_barge_in_cooldown_seconds: float = Field(default=1.0, ge=0.0, le=5.0, description="Cooldown window after an interruption during which new local interruptions are suppressed")
    voice_local_barge_in_during_playback: bool = Field(
        default=False,
        description="Whether to allow local RMS detector to interrupt during speaker playback (False lets Gemini Server VAD drive authoritative interruptions to prevent acoustic echo self-interruption)",
    )
    voice_headphones_mode: bool = Field(
        default=False,
        description="Whether headphones are used (enables local barge-in during playback with lower threshold)",
    )
    voice_biometrics_enabled: bool = Field(
        default=False,
        description="Enroll and verify the owner's voice before obeying spoken commands (resemblyzer; enroll with 'friday --enroll-voice')",
    )
    voice_adaptive_noise_alpha: float = Field(default=0.05, ge=0.001, le=0.5, description="Exponential moving average alpha for tracking ambient noise floor")
    voice_adaptive_noise_multiplier: float = Field(default=3.5, ge=1.5, le=10.0, description="Adaptive noise floor multiplier to declare candidate speech")
    voice_thinking_level: str = Field(
        default="MINIMAL",
        description="Thinking level for Gemini 3.1 Live session: MINIMAL, LOW, MEDIUM, HIGH",
    )
    voice_thinking_budget: int | None = Field(default=0, ge=0, le=2048, description="Deprecated: Thinking budget tokens for legacy models")

    # Vision & Multimodal Settings
    vision_model: str = Field(
        default="gemini-3.6-flash",
        description="Multimodal Gemini vision model identifier",
    )
    vision_provider: str = Field(
        default="gemini",
        description="Vision provider: 'gemini' or 'mock'",
    )
    vision_max_image_bytes: int = Field(
        default=20971520,  # 20 MB
        description="Maximum allowed image size in bytes for visual analysis",
    )
    screen_capture_provider: str = Field(
        default="windows",
        description="Screen capture provider backend: 'windows' or 'mock'",
    )
    screen_display: str = Field(
        default="primary",
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
        description="Whether background periodic screen awareness is enabled (default False)",
    )
    screen_interval_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=3600.0,
        description="Minimum interval in seconds between periodic screen captures",
    )
    screen_change_threshold: float = Field(
        default=0.05,
        ge=0.001,
        le=1.0,
        description="Minimum image difference ratio (0.0 to 1.0) required to trigger visual analysis for changed screens",
    )
    proactive_watcher_enabled: bool = Field(
        default=False,
        description="Enable Proactive Screen Reading Proactive Screen Reading (The Watcher)",
    )
    watcher_interval_seconds: float = Field(
        default=120.0,
        ge=30.0,
        le=3600.0,
        description="Interval in seconds between proactive screen watcher checks",
    )

    tesseract_cmd: str | None = Field(
        default=r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.name == "nt" else None,
        description="Path to Tesseract OCR executable (e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe on Windows)",
    )

    task_enabled: bool = Field(default=False, description="Enable proactive task automation")
    task_max_calls: int = Field(default=100, description="Maximum allowed LLM calls per task")
    task_retry_limit: int = Field(default=3, description="Maximum retry attempts for transient failures")
    task_daily_cap: int | None = Field(default=None, description="Optional cap on total daily task executions")
    task_circuit_breaker_threshold: int = Field(default=5, description="Consecutive failure count before disabling a task")

    # FORGE (Autonomous Software Engineering Engine) Integration
    forge_api_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for FORGE Software Engineering API",
    )
    forge_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for FORGE Software Engineering API",
    )
    forge_api_key: str | None = Field(
        default=None,
        description="API Key for FORGE authentication and HMAC signing",
    )
    forge_enabled: bool = Field(
        default=True,
        description="Enable FORGE ecosystem integration",
    )
    forge_max_concurrent_tasks: int = Field(
        default=3,
        description="Maximum concurrent tasks dispatched to FORGE",
    )
    forge_task_timeout: int = Field(
        default=1800,
        description="Default timeout in seconds for FORGE tasks (default: 30 minutes)",
    )
    forge_supervision_interval_seconds: int = Field(
        default=60,
        description="Polling interval in seconds for FORGE task supervision",
    )
    forge_health_check_interval_seconds: int = Field(
        default=300,
        description="Polling interval in seconds for FORGE health monitoring",
    )

    # Unified Ecosystem Command Center
    ecosystem_enabled: bool = Field(
        default=True,
        description="Enable unified ecosystem command center across Bot, FORGE, and AI-Universe",
    )
    trading_bot_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for Algorithmic Trading Bot API (Stratex)",
    )
    ai_universe_base_url: str = Field(
        default="http://localhost:8001",
        description="Base URL for AI-Universe / Inference Core API",
    )
    intelx_base_url: str = Field(
        default="http://localhost:8002",
        description="Base URL for IntelX Evidence & Research API",
    )
    futuris_base_url: str = Field(
        default="http://localhost:8003",
        description="Base URL for Futuris Predictive Forecasting API",
    )
    memora_base_url: str = Field(
        default="http://localhost:8004",
        description="Base URL for Memora Universal Memory API",
    )
    sentinel_base_url: str = Field(
        default="http://localhost:8003",
        description="Base URL for Sentinel Security API",
    )

    # CORTEX / NEXUS (Autonomous Website & Growth Engine) Integration
    nexus_base_url: str = Field(
        default="http://localhost:8005",
        description="Base URL for Cortex / Nexus Autonomous Website & Growth API",
    )
    nexus_enabled: bool = Field(
        default=True,
        description="Enable Cortex autonomous growth & website integration",
    )
    nexus_vigilance_interval_seconds: int = Field(
        default=60,
        description="Polling interval in seconds for Cortex vigilance operator",
    )

    def get_diagnostics(self) -> dict[str, Any]:
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

    @property
    def sqlite_db_path(self) -> str:
        """Compatibility accessor for memory_db_path."""
        return self.memory_db_path

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
