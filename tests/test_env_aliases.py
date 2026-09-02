import os
import pytest
from friday.core.config import Settings

# The same map from config.py handle_legacy_aliases
LEGACY_ALIASES = {
    'FRIDAY_IOT_HUB_URL': ['IOT_HUB_URL', 'iot_hub_url'],
    'FRIDAY_IOT_HUB_TOKEN': ['IOT_HUB_TOKEN', 'iot_hub_token'],
    'FRIDAY_CALENDAR_ICS_URL': ['CALENDAR_ICS_URL', 'calendar_ics_url'],
    'FRIDAY_EMAIL_ADDRESS': ['EMAIL_ADDRESS', 'email_address'],
    'FRIDAY_EMAIL_APP_PASSWORD': ['EMAIL_APP_PASSWORD', 'email_app_password'],
    'FRIDAY_EMAIL_SMTP_HOST': ['EMAIL_SMTP_HOST', 'email_smtp_host'],
    'FRIDAY_EMAIL_SMTP_PORT': ['EMAIL_SMTP_PORT', 'email_smtp_port'],
    'FRIDAY_ACTIVE_DEVICE': ['ACTIVE_DEVICE', 'active_device'],
    'FRIDAY_UNIVERSE_API_URL': ['AI_UNIVERSE_API_URL', 'FRIDAY_AI_UNIVERSE_API_URL', 'universe_api_url'],
    'FRIDAY_VOICE_ENABLED': ['VOICE_ENABLED', 'voice_enabled'],
    'FRIDAY_AUDIO_INPUT_DEVICE': ['AUDIO_INPUT_DEVICE', 'audio_input_device'],
    'FRIDAY_AUDIO_OUTPUT_DEVICE': ['AUDIO_OUTPUT_DEVICE', 'audio_output_device'],
    'FRIDAY_VOICE_NAME': ['VOICE_NAME', 'voice_name'],
    'FRIDAY_VOICE_LIVE_MODEL': ['VOICE_LIVE_MODEL', 'voice_live_model'],
    'FRIDAY_VOICE_VAD_START_SENSITIVITY': ['VOICE_VAD_START_SENSITIVITY', 'voice_vad_start_sensitivity'],
    'FRIDAY_VOICE_VAD_END_SENSITIVITY': ['VOICE_VAD_END_SENSITIVITY', 'voice_vad_end_sensitivity'],
    'FRIDAY_VOICE_SPEAKER_TIMEOUT_MS': ['VOICE_SPEAKER_TIMEOUT_MS', 'voice_speaker_timeout_ms', 'speaker_timeout_ms'],
    'FRIDAY_VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK': ['VOICE_LOCAL_BARGE_IN_DURING_PLAYBACK', 'voice_local_barge_in_during_playback'],
    'FRIDAY_VOICE_HEADPHONES_MODE': ['VOICE_HEADPHONES_MODE', 'voice_headphones_mode'],
    'FRIDAY_VOICE_BIOMETRICS_ENABLED': ['VOICE_BIOMETRICS_ENABLED', 'voice_biometrics_enabled'],
    'FRIDAY_VOICE_THINKING_LEVEL': ['VOICE_THINKING_LEVEL', 'voice_thinking_level'],
    'FRIDAY_VISION_MODEL': ['VISION_MODEL', 'vision_model'],
    'FRIDAY_VISION_PROVIDER': ['VISION_PROVIDER', 'vision_provider'],
    'FRIDAY_SCREEN_CAPTURE_PROVIDER': ['SCREEN_CAPTURE_PROVIDER', 'screen_capture_provider'],
    'FRIDAY_SCREEN_DISPLAY': ['SCREEN_DISPLAY', 'screen_display'],
    'FRIDAY_SCREEN_AWARE': ['SCREEN_AWARE', 'screen_aware'],
    'FRIDAY_SCREEN_INTERVAL_SECONDS': ['SCREEN_INTERVAL_SECONDS', 'screen_interval_seconds'],
    'FRIDAY_SCREEN_CHANGE_THRESHOLD': ['SCREEN_CHANGE_THRESHOLD', 'screen_change_threshold'],
    'FRIDAY_PROACTIVE_WATCHER_ENABLED': ['PROACTIVE_WATCHER_ENABLED', 'proactive_watcher_enabled'],
    'FRIDAY_WATCHER_INTERVAL_SECONDS': ['WATCHER_INTERVAL_SECONDS', 'watcher_interval_seconds'],
    'FRIDAY_TESSERACT_CMD': ['TESSERACT_CMD', 'tesseract_cmd'],
    'FRIDAY_FORGE_BASE_URL': ['FORGE_BASE_URL', 'FRIDAY_FORGE_API_URL', 'FORGE_API_URL', 'forge_api_url', 'forge_base_url'],
    'FRIDAY_FORGE_API_KEY': ['FORGE_API_KEY', 'forge_api_key'],
    'FRIDAY_FORGE_ENABLED': ['FORGE_ENABLED', 'forge_enabled'],
    'FRIDAY_FORGE_MAX_CONCURRENT_TASKS': ['FORGE_MAX_CONCURRENT_TASKS', 'forge_max_concurrent_tasks'],
    'FRIDAY_FORGE_TASK_TIMEOUT': ['FORGE_TASK_TIMEOUT', 'forge_task_timeout'],
    'FRIDAY_FORGE_SUPERVISION_INTERVAL_SECONDS': ['FORGE_SUPERVISION_INTERVAL_SECONDS', 'forge_supervision_interval_seconds'],
    'FRIDAY_FORGE_HEALTH_CHECK_INTERVAL_SECONDS': ['FORGE_HEALTH_CHECK_INTERVAL_SECONDS', 'forge_health_check_interval_seconds'],
    'FRIDAY_ECOSYSTEM_ENABLED': ['ECOSYSTEM_ENABLED', 'ecosystem_enabled'],
    'FRIDAY_STRATEX_URL': ['STRATEX_URL', 'FRIDAY_TRADING_BOT_BASE_URL', 'TRADING_BOT_BASE_URL', 'trading_bot_base_url'],
    'FRIDAY_INFERENCE_URL': ['INFERENCE_URL', 'FRIDAY_AI_UNIVERSE_BASE_URL', 'AI_UNIVERSE_BASE_URL', 'ai_universe_base_url'],
    'FRIDAY_INTELX_URL': ['INTELX_URL', 'intelx_base_url'],
    'FRIDAY_FUTURIS_URL': ['FUTURIS_URL', 'futuris_base_url'],
    'FRIDAY_MEMORA_URL': ['MEMORA_URL', 'memora_base_url'],
    'FRIDAY_SENTINEL_URL': ['SENTINEL_URL', 'sentinel_base_url'],
    'FRIDAY_CORTEX_URL': ['CORTEX_URL', 'NEXUS_URL', 'FRIDAY_NEXUS_BASE_URL', 'NEXUS_BASE_URL', 'nexus_base_url'],
    'FRIDAY_NEXUS_ENABLED': ['NEXUS_ENABLED', 'CORTEX_ENABLED', 'nexus_enabled'],
    'FRIDAY_NEXUS_VIGILANCE_INTERVAL_SECONDS': ['NEXUS_VIGILANCE_INTERVAL_SECONDS', 'nexus_vigilance_interval_seconds']
}

@pytest.mark.parametrize("canonical, aliases", LEGACY_ALIASES.items())
def test_deprecation_warnings_for_aliases(canonical, aliases, monkeypatch):
    for alias in [aliases[0]]:
        monkeypatch.delenv(canonical, raising=False)
        monkeypatch.setenv(alias, "1")
        with pytest.warns(DeprecationWarning, match=f"Environment variable '{alias}' is deprecated"):
            try:
                Settings(_env_file=None)
            except Exception:
                pass
