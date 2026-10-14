"""Startup pre-flight validation and environment integrity checks for FRIDAY Core."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("friday.core.startup_validator")


class StartupValidationError(Exception):
    """Raised when environment or critical dependencies fail pre-flight validation."""


def validate_runtime_environment(fail_fast: bool = False) -> dict[str, Any]:
    """Validate critical environment variables and directories at server startup.
    
    Checks for presence of essential configuration, verifies working directories,
    and returns a summary report. In production mode, can fail-fast on critical misconfigurations.
    """
    env = os.getenv("FRIDAY_ENV", "production").lower()
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Check data directory write permissions
    data_dir = Path(os.getenv("FRIDAY_DATA_DIR", "data"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        issues.append(f"Data directory '{data_dir}' is not writable: {exc}")

    # 2. Check PORT variable if present
    port_str = os.getenv("PORT")
    if port_str:
        try:
            port_int = int(port_str)
            if not (1 <= port_int <= 65535):
                issues.append(f"PORT '{port_str}' is out of range 1..65535")
        except ValueError:
            issues.append(f"PORT environment variable must be an integer, got '{port_str}'")

    # 2. Check provider credentials in production
    provider = os.getenv("FRIDAY_LLM_PROVIDER", "chain").lower()
    if env == "production":
        groq_key = os.getenv("FRIDAY_GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
        gemini_key = os.getenv("FRIDAY_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
        openrouter_key = os.getenv("FRIDAY_OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        mistral_key = os.getenv("FRIDAY_MISTRAL_API_KEY") or os.getenv("MISTRAL_API_KEY")

        if provider == "chain" and not any([groq_key, gemini_key, openrouter_key, mistral_key]):
            warnings.append(
                "No external LLM API keys detected for provider 'chain'. Core will fall back to local/mock reasoning. "
                "See .env.example for configuration."
            )

    report = {
        "valid": len(issues) == 0,
        "environment": env,
        "issues": issues,
        "warnings": warnings,
    }

    if issues:
        msg = "FRIDAY Startup Pre-flight Validation Failed:\n" + "\n".join(f" - {i}" for i in issues)
        msg += "\nPlease review your configuration and refer to .env.example."
        logger.critical(msg)
        if fail_fast:
            raise StartupValidationError(msg)
    elif warnings:
        for w in warnings:
            logger.warning("Startup Pre-flight Warning: %s", w)

    return report
