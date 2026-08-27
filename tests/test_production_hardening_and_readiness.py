# -*- coding: utf-8 -*-
"""Comprehensive Test Suite for FRIDAY Final Production Hardening & Operational Readiness."""

import os
import shutil
import tempfile
import time
import pytest

from friday.core.backup_recovery import BackupRecoveryManager
from friday.diagnostics.doctor_enhanced import FridayDoctorEnhanced
from friday.optimization.production_optimizer import LazySubsystemConnector, ProductionOptimizer
from friday.security.production_hardening import (
    BiometricSecurityEngine,
    CredentialScrubber,
    CredentialVault,
    IntrusionDetector,
    RateLimiter,
)


@pytest.fixture
def production_setup():
    temp_backup_dir = tempfile.mkdtemp()
    vault = CredentialVault()
    biometric = BiometricSecurityEngine(min_confidence=0.95, max_failed_attempts=5, lockout_duration_minutes=15)
    limiter = RateLimiter(max_requests_per_minute=5)
    intrusion = IntrusionDetector()
    backup_mgr = BackupRecoveryManager(backup_dir=temp_backup_dir, retention_days=7)
    optimizer = ProductionOptimizer()
    doctor = FridayDoctorEnhanced()

    yield vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_backup_dir
    shutil.rmtree(temp_backup_dir, ignore_errors=True)


# =========================================================================
# 1. Security Hardening Tests
# =========================================================================

def test_credential_vault_and_scrubbing(production_setup):
    """Verify Fernet encryption at rest and universal credential scrubbing."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Vault Storage & Decryption
    vault.store_secret("BINANCE_API_KEY", "prod_secret_key_8849204859")
    retrieved = vault.retrieve_secret("BINANCE_API_KEY")
    assert retrieved == "prod_secret_key_8849204859"

    # 2. Universal Credential Scrubber
    raw_log = "Error connecting with api_key='secret12345678' and token sk-proj99384928472948274829"
    scrubbed = CredentialScrubber.scrub_text(raw_log)
    assert "secret12345678" not in scrubbed
    assert "[REDACTED_OPENAI_KEY]" in scrubbed

    dict_data = {"user": "admin", "api_key": "raw_key", "nested": {"password": "pass"}}
    scrubbed_dict = CredentialScrubber.scrub_dict(dict_data)
    assert scrubbed_dict["api_key"] == "[REDACTED_SECRET]"
    assert scrubbed_dict["nested"]["password"] == "[REDACTED_SECRET]"


def test_biometric_security_and_15min_lockout(production_setup):
    """Verify voice biometric confidence checks and 5-attempt / 15-minute lockout."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Low confidence fails
    res_low = biometric.verify_biometric_command("Confirmed, authorization alpha-niner", detected_confidence=0.85)
    assert res_low.is_authorized is False

    # 2. Missing phrase fails
    res_no_phrase = biometric.verify_biometric_command("Hello please stop trading", detected_confidence=0.98)
    assert res_no_phrase.is_authorized is False

    # 3. High confidence + Valid Phrase succeeds
    res_ok = biometric.verify_biometric_command("Confirmed, authorization alpha-niner", detected_confidence=0.97)
    assert res_ok.is_authorized is True

    # 4. 5 Failed attempts trigger Lockout
    for _ in range(5):
        biometric.verify_biometric_command("bad phrase", detected_confidence=0.50)

    locked, remaining = biometric.is_locked_out()
    assert locked is True
    assert remaining > 0

    # Command during lockout rejected
    res_locked = biometric.verify_biometric_command("Confirmed, authorization alpha-niner", detected_confidence=0.99)
    assert res_locked.is_authorized is False
    assert res_locked.is_locked_out is True


def test_rate_limiting_and_intrusion_detection(production_setup):
    """Verify API rate limiting (sliding window) and intrusion detection."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Rate Limiting (limit is 5 in test fixture)
    for _ in range(5):
        allowed, rem, _ = limiter.allow_request("client_1")
        assert allowed is True

    blocked, _, retry_after = limiter.allow_request("client_1")
    assert blocked is False
    assert retry_after > 0

    # 2. Intrusion Detection: Prohibited Payload
    alert = intrusion.audit_command_attempt("sudo rm -rf /etc/data")
    assert alert is not None
    assert alert.severity == "CRITICAL"
    assert "prohibited security signature" in alert.details


# =========================================================================
# 2. State Backup, Recovery & Rollback Tests
# =========================================================================

def test_state_backup_and_recovery(production_setup):
    """Verify 6-hour snapshots, config backups, and point-in-time restoration."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Create Periodic 6h Snapshot
    snap = backup_mgr.create_snapshot(
        snapshot_type="PERIODIC_6H",
        user_preferences={"voice_persona": "FRI_EXECUTIVE", "max_drawdown_pct": 4.5},
    )
    assert snap.size_bytes > 0
    assert os.path.exists(os.path.join(temp_dir, f"{snap.snapshot_id}.json"))

    # 2. Config Change Auto-Snapshot
    snap_cfg = backup_mgr.snapshot_on_config_change({"trading_bot_url": "http://localhost:5000"})
    assert snap_cfg.snapshot_type == "CONFIG_CHANGE"

    # 3. List and Restore Snapshot
    snaps = backup_mgr.list_snapshots()
    assert len(snaps) >= 2

    restored = backup_mgr.restore_snapshot(snap.snapshot_id)
    assert restored is not None
    assert restored["snapshot_id"] == snap.snapshot_id
    assert restored["user_preferences"]["voice_persona"] == "FRI_EXECUTIVE"


# =========================================================================
# 3. Performance Optimizer & Latency SLA Tests
# =========================================================================

def test_production_optimizer_and_lazy_loading(production_setup):
    """Verify memory leak detection, voice latency benchmarking, and lazy loading."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Memory Profiling
    mem = optimizer.profile_memory()
    assert mem["status"] == "HEALTHY"
    assert optimizer.detect_memory_leaks() is False

    # 2. Voice Pipeline Latency Benchmark (<500ms SLA)
    def dummy_voice_pipeline():
        time.sleep(0.01)  # 10ms
        return "Spoken response"

    bench = optimizer.benchmark_voice_pipeline(dummy_voice_pipeline)
    assert bench.is_compliant is True
    assert bench.latency_ms < 500.0

    # 3. Lazy Subsystem Connector
    connected = False

    def mock_connect():
        nonlocal connected
        connected = True
        return {"session": "active"}

    connector = LazySubsystemConnector("trading_bot", mock_connect)
    assert connector.is_connected is False
    assert connected is False

    # First access establishes connection
    conn = connector.get_connection()
    assert connector.is_connected is True
    assert connected is True
    assert conn["session"] == "active"


# =========================================================================
# 4. Friday Doctor Enhanced 5-Subsystem Diagnostics Tests
# =========================================================================

def test_friday_doctor_enhanced_and_self_healing(production_setup):
    """Verify 5-subsystem health diagnostics, pre-flight checks, and automated healing."""
    vault, biometric, limiter, intrusion, backup_mgr, optimizer, doctor, temp_dir = production_setup

    # 1. Pre-Flight Startup Check
    preflight = doctor.run_preflight_check()
    assert preflight.is_ready_for_startup is True
    assert preflight.checks_passed == preflight.checks_total

    # 2. 5-Subsystem Diagnostics and Automated Healing
    report = doctor.diagnose_and_heal()
    assert report.overall_status == "HEALTHY"
    assert len(report.subsystem_reports) == 5
    assert "friday_core" in report.subsystem_reports
    assert "trading_bot" in report.subsystem_reports
    assert "forge" in report.subsystem_reports
    assert "ai_universe" in report.subsystem_reports
    assert "nexus" in report.subsystem_reports
    assert len(report.healing_actions_taken) == 3
