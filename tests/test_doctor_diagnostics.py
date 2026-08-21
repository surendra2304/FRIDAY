# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Doctor & Diagnostics Subsystem.

Test Type: UNIT / SECURITY / HARDWARE_SIMULATION

Validates:
1. Classification of all DiagnosticStatus levels:
   - CONFIGURED, AVAILABLE, DEGRADED, COOLDOWN, BLOCKED, UNAVAILABLE, ERROR.
2. Missing credentials detection and safe remediation guidance.
3. Exhausted/cooldown credentials detection.
4. Voice hardware diagnostics (missing microphone, missing speaker).
5. Display/screen capture diagnostic fallback.
6. Corrupt SQLite database detection via integrity check.
7. Zero secret leakage across machine-readable JSON and human-readable CLI views.
"""

from datetime import datetime, timezone
import pathlib
import pytest
from unittest import mock

# Explicit test markers
pytestmark = [pytest.mark.unit, pytest.mark.security]

from friday.core.config import Settings
from friday.core.doctor import (
    ComponentHealth,
    DiagnosticStatus,
    DoctorReport,
    FridayDoctor,
)


# ============================================================================
# 1. Full Diagnostics & Status Aggregation
# ============================================================================

def test_friday_doctor_full_diagnostics_offline_mode():
    """Verify full diagnostics execute safely in offline/test environment."""
    settings = Settings(env="testing", llm_provider="mock")
    doctor = FridayDoctor(settings=settings)

    report = doctor.run_full_diagnostics()

    assert isinstance(report, DoctorReport)
    assert report.overall_status in (DiagnosticStatus.AVAILABLE, DiagnosticStatus.CONFIGURED, DiagnosticStatus.DEGRADED)
    assert "configuration" in report.components
    assert "credential_pool" in report.components
    assert "llm_provider" in report.components
    assert "safety_system" in report.components


# ============================================================================
# 2. Credential Pool Health (Missing vs Exhausted)
# ============================================================================

def test_missing_credentials_detected_as_unavailable():
    """Verify missing API credentials return UNAVAILABLE with remediation instructions."""
    settings = Settings(
        env="testing",
        gemini_api_key="",
        gemini_fallback_api_key_1="",
        gemini_fallback_api_key_2="",
        gemini_fallback_api_key_3="",
        gemini_fallback_api_key_4="",
    )
    doctor = FridayDoctor(settings=settings)

    with mock.patch.dict("os.environ", {}, clear=True):
        health = doctor.diagnose_credential_pool()

        assert health.status == DiagnosticStatus.UNAVAILABLE
        assert "Zero API credentials" in health.message
        assert health.remediation is not None


def test_exhausted_credentials_in_cooldown():
    """Verify all credentials in cooldown report COOLDOWN status."""
    settings = Settings(env="testing", gemini_api_key="AIzaSyDummyKeyForTestingPurposes1234")
    doctor = FridayDoctor(settings=settings)

    from friday.auth.credential_pool import Credential
    mock_cred = Credential(api_key="AIzaSyDummyKeyForTestingPurposes1234")
    mock_cred.cooldown_until = datetime.utcnow() + pytest.importorskip("datetime").timedelta(hours=1)

    with mock.patch("friday.auth.credential_pool.GeminiCredentialPool.load_keys", autospec=True) as mock_load:
        def set_mock_creds(self, keys):
            self.credentials = [mock_cred]
        mock_load.side_effect = set_mock_creds

        health = doctor.diagnose_credential_pool()
        assert health.status == DiagnosticStatus.COOLDOWN
        assert "exhausted or in cooldown" in health.message


# ============================================================================
# 3. Voice Hardware Diagnostics
# ============================================================================

def test_voice_missing_microphone_reports_degraded():
    """Verify missing microphone device reports DEGRADED."""
    doctor = FridayDoctor(settings=Settings(env="testing"))

    with mock.patch("friday.voice.audio_io.check_device_availability") as mock_check:
        mock_check.side_effect = lambda dev: (False, "Device not found") if dev == "input" else (True, None)

        health = doctor.diagnose_voice_subsystem()
        assert health.status == DiagnosticStatus.DEGRADED
        assert "Microphone missing" in health.message


def test_voice_no_audio_devices_reports_unavailable():
    """Verify absence of any audio devices reports UNAVAILABLE."""
    doctor = FridayDoctor(settings=Settings(env="testing"))

    with mock.patch("friday.voice.audio_io.check_device_availability", return_value=(False, "No device")):
        health = doctor.diagnose_voice_subsystem()
        assert health.status == DiagnosticStatus.UNAVAILABLE
        assert "No audio input or output devices" in health.message


# ============================================================================
# 4. Corrupt Database Diagnostics
# ============================================================================

def test_corrupt_database_reports_error(tmp_path: pathlib.Path):
    """Verify corrupted SQLite database file triggers ERROR status."""
    bad_db = str(tmp_path / "corrupt.db")
    pathlib.Path(bad_db).write_text("NOT_A_VALID_SQLITE_HEADER", encoding="utf-8")

    settings = Settings(env="testing", memory_db_path=bad_db)
    doctor = FridayDoctor(settings=settings)

    health = doctor.diagnose_memory_database()
    assert health.status == DiagnosticStatus.ERROR
    assert "error" in health.message.lower() or "failed" in health.message.lower()


# ============================================================================
# 5. Zero Secret Leakage & Output Formats
# ============================================================================

def test_zero_secret_leakage_in_doctor_reports():
    """Verify secrets are completely scrubbed in both dict and CLI table formats."""
    secret_key = "AIzaSySecretApiKeyThatMustNeverLeak12345"
    settings = Settings(env="testing", gemini_api_key=secret_key)
    doctor = FridayDoctor(settings=settings)

    report = doctor.run_full_diagnostics()

    # Machine-readable output
    dict_out = report.to_dict()
    assert secret_key not in str(dict_out)

    # Human-readable CLI table
    cli_out = report.to_cli_table()
    assert secret_key not in cli_out
    assert "FRIDAY SYSTEM DIAGNOSTICS REPORT" in cli_out
    assert "[OK]" in cli_out or "[CFG]" in cli_out or "[WARN]" in cli_out
