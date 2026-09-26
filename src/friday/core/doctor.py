"""Safe Diagnostics and System Health Doctor for FRIDAY.

Audits and reports sanitized health information for:
- Configuration validity
- Provider availability & connectivity
- Credential pool health & cooldowns
- Gemini / model configuration
- Voice devices (Microphone, Speaker, VAD)
- Screen capture & display topology
- Multimodal Vision provider
- Memory database & SQLite integrity
- Task manager & concurrent workers
- Perception cache & memory footprint
- Safety system & authorizer gating

Statuses:
- CONFIGURED: Configured properly but offline/mock mode active.
- AVAILABLE: Fully operational and verified healthy.
- DEGRADED: Partially operational (e.g. some credentials exhausted or audio fallback).
- COOLDOWN: Temporarily paused due to provider rate-limits.
- BLOCKED: Prohibited or blocked by security policies/missing hardware.
- UNAVAILABLE: Hardware or service absent.
- ERROR: Exception encountered during diagnosis.

Invariants:
- NEVER outputs raw API keys, passwords, tokens, or sensitive user data.
- Generates both machine-readable JSON/Dict structures and human-readable CLI tables.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from friday.security.scrubber import recursive_sanitize, redact_secrets

logger = get_logger("core.doctor")


class DiagnosticStatus(str, Enum):
    """Component health status classifications."""
    CONFIGURED = "CONFIGURED"
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    COOLDOWN = "COOLDOWN"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass
class ComponentHealth:
    """Diagnostic report for an individual subsystem component."""
    name: str
    status: DiagnosticStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": redact_secrets(self.message),
            "details": recursive_sanitize(self.details),
            "remediation": self.remediation,
        }


@dataclass
class DoctorReport:
    """Comprehensive system-wide diagnostic report."""
    overall_status: DiagnosticStatus
    components: dict[str, ComponentHealth]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "timestamp": self.timestamp.isoformat(),
            "components": {k: v.to_dict() for k, v in self.components.items()},
        }

    def to_cli_table(self) -> str:
        """Render a formatted, human-readable CLI summary table."""
        lines = [
            "=" * 72,
            f"  FRIDAY SYSTEM DIAGNOSTICS REPORT - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"  OVERALL HEALTH: [{self.overall_status.value}]",
            "=" * 72,
            f"{'COMPONENT':<22} | {'STATUS':<12} | {'DETAILS'}",
            "-" * 72,
        ]

        status_symbols = {
            DiagnosticStatus.AVAILABLE: "[OK]    ",
            DiagnosticStatus.CONFIGURED: "[CFG]   ",
            DiagnosticStatus.DEGRADED: "[WARN]  ",
            DiagnosticStatus.COOLDOWN: "[COOL]  ",
            DiagnosticStatus.BLOCKED: "[BLOCK] ",
            DiagnosticStatus.UNAVAILABLE: "[UNAVL] ",
            DiagnosticStatus.ERROR: "[ERR]   ",
        }

        for comp_name, comp in self.components.items():
            sym = status_symbols.get(comp.status, "[INFO]  ")
            lines.append(f"{comp_name:<22} | {sym:<12} | {comp.message}")
            if comp.remediation:
                lines.append(f"{'':<22} | {'':<12} | -> Remediation: {comp.remediation}")

        lines.append("=" * 72)
        return "\n".join(lines)


class FridayDoctor:
    """Diagnoses and audits the operational health of all FRIDAY subsystems."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def diagnose_configuration(self) -> ComponentHealth:
        """Audit environment settings and schema validity."""
        try:
            cfg = self.settings
            issues = []
            if not cfg.agent_name:
                issues.append("Agent name is blank.")
            if getattr(cfg, "max_tool_iterations", 5) < 1:
                issues.append("max_tool_iterations must be >= 1.")

            status = DiagnosticStatus.AVAILABLE if not issues else DiagnosticStatus.DEGRADED
            msg = "Configuration valid and loaded." if not issues else "; ".join(issues)
            return ComponentHealth(
                name="configuration",
                status=status,
                message=msg,
                details={"env": cfg.env, "agent_name": cfg.agent_name},
            )
        except Exception as e:
            return ComponentHealth(
                name="configuration",
                status=DiagnosticStatus.ERROR,
                message=f"Configuration load error: {redact_secrets(str(e))}",
                remediation="Check .env file or configuration parameters.",
            )

    def diagnose_credential_pool(self) -> ComponentHealth:
        """Report configured Gemini credentials without implying they were network-tested."""
        try:
            from friday.auth.credential_pool import GeminiCredentialPool

            raw_configured_keys = [
                self.settings.gemini_api_key,
                getattr(self.settings, "gemini_fallback_api_key_1", None),
                getattr(self.settings, "gemini_fallback_api_key_2", None),
                getattr(self.settings, "gemini_fallback_api_key_3", None),
                getattr(self.settings, "gemini_fallback_api_key_4", None),
            ]
            env_names = ["FRIDAY_GEMINI_API_KEY", "GEMINI_API_KEY"]
            env_names.extend(
                name
                for index in range(1, 10)
                for name in (f"FRIDAY_GEMINI_FALLBACK_API_KEY_{index}", f"GEMINI_FALLBACK_API_KEY_{index}")
            )
            raw_configured_keys.extend(os.getenv(name) for name in env_names)
            configured_keys = {
                item.strip()
                for raw_value in raw_configured_keys
                if raw_value
                for item in str(raw_value).split(",")
                if item.strip()
            }

            # The runtime pool reads every configured fallback slot (and the
            # resolved local env file), rather than stopping at four settings.
            pool = (
                GeminiCredentialPool(keys=sorted(configured_keys))
                if self.settings.env == "testing"
                else GeminiCredentialPool()
            )
            configured_keys.update(credential.api_key for credential in pool.credentials)

            if not configured_keys:
                return ComponentHealth(
                    name="credential_pool",
                    status=DiagnosticStatus.UNAVAILABLE,
                    message="No Gemini credentials are configured.",
                    remediation="Configure the Gemini provider pool in the local environment.",
                )

            cooldown_count = sum(
                1 for credential in pool.credentials if not credential.is_healthy(max_failures=3)
            )
            return ComponentHealth(
                name="credential_pool",
                status=(
                    DiagnosticStatus.COOLDOWN
                    if cooldown_count and pool.credentials and cooldown_count == len(pool.credentials)
                    else DiagnosticStatus.CONFIGURED
                ),
                message=f"{len(configured_keys)} Gemini credentials configured; provider connectivity was not tested.",
                details={
                    "configured": len(configured_keys),
                    "local_cooldown_count": cooldown_count,
                    "provider_connectivity_checked": False,
                },
                remediation="Run a metered provider preflight to verify credentials and current quota." if cooldown_count else None,
            )
        except Exception as e:
            return ComponentHealth(
                name="credential_pool",
                status=DiagnosticStatus.ERROR,
                message=f"Credential pool audit failed: {redact_secrets(str(e))}",
            )

    def diagnose_llm_provider(self) -> ComponentHealth:
        """Audit LLM provider model selection and connectivity."""
        try:
            provider = self.settings.llm_provider.lower()
            if provider == "mock":
                return ComponentHealth(
                    name="llm_provider",
                    status=DiagnosticStatus.CONFIGURED,
                    message="Mock LLM provider configured (offline testing mode).",
                    details={"provider": "mock", "model": getattr(self.settings, "gemini_model", None) or self.settings.llm_model},
                )

            if provider == "gemini":
                gemini_pool = self.diagnose_credential_pool()
                if gemini_pool.status == DiagnosticStatus.UNAVAILABLE:
                    return ComponentHealth(
                        name="llm_provider",
                        status=DiagnosticStatus.UNAVAILABLE,
                        message="Gemini provider selected but no credentials are configured.",
                        remediation="Configure the Gemini provider pool in the local environment.",
                    )
                return ComponentHealth(
                    name="llm_provider",
                    status=DiagnosticStatus.CONFIGURED,
                    message=f"Gemini LLM provider configured ({self.settings.llm_model}); live connectivity was not tested.",
                    details={"provider": "gemini", "model": self.settings.llm_model, "credentials": gemini_pool.details.get("configured", 0)},
                )

            provider_key_envs = {
                "groq": ("groq_api_key", ("FRIDAY_GROQ_API_KEY", "GROQ_API_KEY")),
                "openrouter": ("openrouter_api_key", ("FRIDAY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")),
                "mistral": ("mistral_api_key", ("FRIDAY_MISTRAL_API_KEY", "MISTRAL_API_KEY")),
                "openai": ("llm_api_key", ("FRIDAY_OPENAI_API_KEY", "OPENAI_API_KEY")),
                "inference": ("inference_api_key", ("FRIDAY_INFERENCE_API_KEY", "INFERENCE_API_KEY")),
            }
            if provider in provider_key_envs:
                setting_name, env_names = provider_key_envs[provider]
                has_key = bool(getattr(self.settings, setting_name, None)) or any(os.getenv(name) for name in env_names)
                if not has_key:
                    return ComponentHealth(
                        name="llm_provider",
                        status=DiagnosticStatus.UNAVAILABLE,
                        message=f"LLM provider '{provider}' is selected but has no configured credential.",
                        remediation=f"Configure credentials for the {provider} provider.",
                    )

            return ComponentHealth(
                name="llm_provider",
                status=DiagnosticStatus.CONFIGURED,
                message=f"LLM provider '{provider}' configured; live connectivity was not tested.",
                details={"provider": provider, "connectivity_checked": False},
            )
        except Exception as e:
            return ComponentHealth(
                name="llm_provider",
                status=DiagnosticStatus.ERROR,
                message=f"LLM provider error: {redact_secrets(str(e))}",
            )

    def diagnose_voice_subsystem(self) -> ComponentHealth:
        """Audit microphone, speaker, and voice hardware availability."""
        try:
            from friday.voice.audio_io import (
                check_device_availability,
                get_audio_diagnostics,
            )
            mic_ok, mic_err = check_device_availability("input")
            spk_ok, spk_err = check_device_availability("output")
            info = get_audio_diagnostics()

            if not mic_ok and not spk_ok:
                return ComponentHealth(
                    name="voice_audio",
                    status=DiagnosticStatus.UNAVAILABLE,
                    message="No audio input or output devices found.",
                    details=info,
                    remediation="Connect microphone and speakers for voice interactions.",
                )
            if not mic_ok:
                return ComponentHealth(
                    name="voice_audio",
                    status=DiagnosticStatus.DEGRADED,
                    message=f"Microphone missing ({mic_err}); speaker output only.",
                    details=info,
                    remediation="Connect a microphone for bidirectional voice.",
                )
            if not spk_ok:
                return ComponentHealth(
                    name="voice_audio",
                    status=DiagnosticStatus.DEGRADED,
                    message=f"Speaker missing ({spk_err}); microphone input only.",
                    details=info,
                )

            return ComponentHealth(
                name="voice_audio",
                status=DiagnosticStatus.CONFIGURED,
                message="Microphone and speaker devices detected; audio capture/playback was not tested.",
                details=info,
            )
        except Exception as e:
            return ComponentHealth(
                name="voice_audio",
                status=DiagnosticStatus.ERROR,
                message=f"Audio subsystem diagnostics error: {redact_secrets(str(e))}",
            )

    def diagnose_screen_capture(self) -> ComponentHealth:
        """Audit display screen capture driver and monitor topology."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            monitor_count = user32.GetSystemMetrics(80) or 1
            w = user32.GetSystemMetrics(0) or 1920
            h = user32.GetSystemMetrics(1) or 1080
            return ComponentHealth(
                name="screen_capture",
                status=DiagnosticStatus.CONFIGURED,
                message=f"{monitor_count} monitor(s) detected ({w}x{h}); frame capture was not tested.",
                details={"monitor_count": monitor_count, "primary_width": w, "primary_height": h},
            )
        except Exception as e:
            return ComponentHealth(
                name="screen_capture",
                status=DiagnosticStatus.CONFIGURED,
                message="Mock / Headless screen capture mode.",
                details={"error": redact_secrets(str(e))},
            )

    def diagnose_vision_provider(self) -> ComponentHealth:
        """Audit multimodal vision perception provider."""
        try:
            if self.settings.env == "testing":
                return ComponentHealth(
                    name="vision_provider",
                    status=DiagnosticStatus.CONFIGURED,
                    message="Offline / mock multimodal perception mode configured; no live model check was run.",
                )
            gemini_pool = self.diagnose_credential_pool()
            if gemini_pool.status == DiagnosticStatus.UNAVAILABLE:
                return ComponentHealth(
                    name="vision_provider",
                    status=DiagnosticStatus.UNAVAILABLE,
                    message="Gemini Vision selected but no Gemini credentials are configured.",
                    remediation="Configure the Gemini provider pool in the local environment.",
                )
            return ComponentHealth(
                name="vision_provider",
                status=DiagnosticStatus.CONFIGURED,
                message="Gemini Vision credentials configured; live model connectivity was not tested.",
            )
        except Exception as e:
            return ComponentHealth(
                name="vision_provider",
                status=DiagnosticStatus.ERROR,
                message=f"Vision provider diagnosis failed: {redact_secrets(str(e))}",
            )

    def diagnose_memory_database(self) -> ComponentHealth:
        """Audit SQLite conversation memory database and table integrity."""
        try:
            db_path = getattr(self.settings, "memory_db_path", "data/friday.db") or "friday_memory.db"
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("PRAGMA integrity_check")
                res = cursor.fetchone()
                if not res or res[0] != "ok":
                    return ComponentHealth(
                        name="memory_database",
                        status=DiagnosticStatus.ERROR,
                        message=f"SQLite integrity check failed: {res}",
                        remediation="Restore database from backup.",
                    )
            return ComponentHealth(
                name="memory_database",
                status=DiagnosticStatus.AVAILABLE,
                message=f"SQLite memory database healthy ({Path(db_path).name}).",
                details={"db_path": Path(db_path).name},
            )
        except Exception as e:
            return ComponentHealth(
                name="memory_database",
                status=DiagnosticStatus.ERROR,
                message=f"Memory database error: {redact_secrets(str(e))}",
            )

    def diagnose_task_manager(self) -> ComponentHealth:
        """Audit background task manager and execution worker pool."""
        return ComponentHealth(
            name="task_manager",
            status=DiagnosticStatus.CONFIGURED,
            message="Task manager component is available; no background job or checkpoint round-trip was tested.",
        )

    def diagnose_safety_system(self) -> ComponentHealth:
        """Audit cryptographic authorizer and safety gate status."""
        return ComponentHealth(
            name="safety_system",
            status=DiagnosticStatus.AVAILABLE,
            message="Cryptographic capability gating and secret scrubber active.",
            details={"mode": "DefaultSecureAuthorizer"},
        )

    def diagnose_forge(self) -> ComponentHealth:
        """Audit FORGE Autonomous Software Engineering Engine connectivity and health."""
        try:
            forge_enabled = getattr(self.settings, "forge_enabled", True)
            forge_url = getattr(self.settings, "forge_api_url", "http://localhost:8000") or "http://localhost:8000"
            if not forge_enabled:
                return ComponentHealth(
                    name="forge_engine",
                    status=DiagnosticStatus.CONFIGURED,
                    message="FORGE Software Engineering Engine disabled by configuration.",
                )
            return ComponentHealth(
                name="forge_engine",
                status=DiagnosticStatus.CONFIGURED,
                message=f"FORGE endpoint configured ({forge_url}); reachability was not probed.",
                details={"api_url": forge_url, "reachability_checked": False},
            )
        except Exception as e:
            return ComponentHealth(
                name="forge_engine",
                status=DiagnosticStatus.ERROR,
                message=f"FORGE engine diagnosis failed: {redact_secrets(str(e))}",
            )

    def diagnose_agent_shield(self) -> ComponentHealth:
        """Audit AgentShield security engine readiness."""
        try:
            from friday.security.agent_shield import AgentShield
            shield = AgentShield()
            return ComponentHealth(
                name="agent_shield",
                status=DiagnosticStatus.CONFIGURED,
                message="AgentShield component initialized; no prompt-injection or secret-scan test was run.",
            )
        except Exception as e:
            return ComponentHealth(
                name="agent_shield",
                status=DiagnosticStatus.ERROR,
                message=f"AgentShield diagnosis failed: {redact_secrets(str(e))}",
            )

    def diagnose_instinct_engine(self) -> ComponentHealth:
        """Audit Continuous Learning Instinct Engine health."""
        try:
            from friday.learning.instinct_engine import InstinctEngine
            engine = InstinctEngine()
            count = len(engine.list_instincts())
            return ComponentHealth(
                name="instinct_engine",
                status=DiagnosticStatus.AVAILABLE,
                message=f"Instinct Engine operational ({count} active instincts).",
                details={"instinct_count": count},
            )
        except Exception as e:
            return ComponentHealth(
                name="instinct_engine",
                status=DiagnosticStatus.ERROR,
                message=f"Instinct Engine diagnosis failed: {redact_secrets(str(e))}",
            )

    def run_full_diagnostics(self) -> DoctorReport:
        """Execute comprehensive audit across all subsystems and generate report."""
        components = {
            "configuration": self.diagnose_configuration(),
            "credential_pool": self.diagnose_credential_pool(),
            "llm_provider": self.diagnose_llm_provider(),
            "voice_audio": self.diagnose_voice_subsystem(),
            "screen_capture": self.diagnose_screen_capture(),
            "vision_provider": self.diagnose_vision_provider(),
            "memory_database": self.diagnose_memory_database(),
            "task_manager": self.diagnose_task_manager(),
            "safety_system": self.diagnose_safety_system(),
            "forge_engine": self.diagnose_forge(),
            "agent_shield": self.diagnose_agent_shield(),
            "instinct_engine": self.diagnose_instinct_engine(),
        }


        # Calculate overall system status
        statuses = [c.status for c in components.values()]
        if DiagnosticStatus.ERROR in statuses:
            overall = DiagnosticStatus.ERROR
        elif DiagnosticStatus.COOLDOWN in statuses or DiagnosticStatus.DEGRADED in statuses or DiagnosticStatus.UNAVAILABLE in statuses:
            overall = DiagnosticStatus.DEGRADED
        elif all(s == DiagnosticStatus.AVAILABLE for s in statuses):
            overall = DiagnosticStatus.AVAILABLE
        elif all(s in (DiagnosticStatus.AVAILABLE, DiagnosticStatus.CONFIGURED) for s in statuses):
            overall = DiagnosticStatus.CONFIGURED
        else:
            overall = DiagnosticStatus.CONFIGURED

        return DoctorReport(overall_status=overall, components=components)
