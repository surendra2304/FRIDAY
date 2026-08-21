"""Structured and sanitized logging configuration for FRIDAY."""

import logging
import os
import re
from typing import Optional
from friday.core.config import get_settings


class SecretMaskingFilter(logging.Filter):
    """Logging filter to mask API keys, tokens, and sensitive strings."""

    def __init__(self, secrets_to_mask: Optional[list[str]] = None):
        super().__init__()
        from friday.security.scrubber import global_scrubber
        for s in (secrets_to_mask or []):
            global_scrubber.register_secret(s)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: (self._sanitize(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._sanitize(a) if isinstance(a, str) else a for a in record.args)
        return True

    def _sanitize(self, text: str) -> str:
        from friday.security.scrubber import redact_secrets
        return redact_secrets(text)


class SanitizedFormatter(logging.Formatter):
    """Logging formatter that ensures the final formatted message is sanitized of secrets."""

    def __init__(self, fmt: str, datefmt: str, filter_obj: SecretMaskingFilter):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.filter_obj = filter_obj

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return self.filter_obj._sanitize(formatted)


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    console_level: Optional[int] = None,
) -> logging.Logger:
    """Initialize root and application loggers with sanitization.
    
    Args:
        level: Base log level string (default: from settings.log_level).
        log_file: Path to log file (default: from settings.log_file).
        console_level: Optional override for console stream (e.g. logging.WARNING or logging.CRITICAL).
    """
    settings = get_settings()
    log_level_str = level or settings.log_level
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    target_file = log_file or settings.log_file

    logger = logging.getLogger("friday")
    logger.setLevel(log_level)

    # Avoid duplicate handlers if setup is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # Register credentials automatically from settings and environment variables
    from friday.security.scrubber import global_scrubber
    global_scrubber.register_from_settings(settings)
    global_scrubber.register_from_environment()

    mask_filter = SecretMaskingFilter()

    formatter = SanitizedFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filter_obj=mask_filter,
    )

    # Console Handler (default to console_level or WARNING if normal CLI mode, full level if debug)
    eff_console_level = console_level if console_level is not None else log_level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(eff_console_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(mask_filter)
    logger.addHandler(console_handler)

    # File Handler (always records at full log_level)
    if target_file:
        try:
            log_dir = os.path.dirname(target_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.FileHandler(target_file, encoding="utf-8")
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(mask_filter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Could not initialize file logging at '{target_file}': {e}")

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Obtain a namespaced logger child of 'friday'."""
    if name.startswith("friday."):
        return logging.getLogger(name)
    return logging.getLogger(f"friday.{name}")


# ---------------------------------------------------------------------------
# Safe argument redaction
# ---------------------------------------------------------------------------

# Scalar types that are safe to include verbatim in structured metadata logs.
_SAFE_SCALAR_TYPES = (int, float, bool)

# Argument key names that are explicitly safe to log as values.
_SAFE_ARG_KEYS: frozenset = frozenset(
    {
        "expression",  # calculator expressions (arithmetic only, not secrets)
        "query",       # search queries
        "limit",
        "offset",
        "threshold",
        "mode",
        "action_name",
    }
)

# Argument key names that must always be redacted regardless of value type.
_SENSITIVE_ARG_KEYS: frozenset = frozenset(
    {
        "password", "passwd", "secret", "token", "key", "api_key",
        "authorization", "credential", "credentials", "private",
        "private_key", "access_token", "refresh_token", "auth", "bearer",
        "content",   # arbitrary file contents
        "text",      # arbitrary text blobs
        "data",      # arbitrary binary / user data
        "body",      # HTTP body payloads
        "payload",
    }
)

_MAX_SAFE_STRING_LEN = 120


def redact_tool_args(args: dict, *, max_keys: int = 8) -> dict:
    """Return a log-safe redacted copy of *args* containing only safe metadata.

    Rules (applied per key in order):
    1. Keys in ``_SENSITIVE_ARG_KEYS``  -> ``"[REDACTED]"``.
    2. Values that are ``bool`` or ``int`` or ``float`` -> kept as-is (safe scalars).
    3. Keys in ``_SAFE_ARG_KEYS`` with a **short** string value -> kept as-is.
    4. Everything else (arbitrary strings, lists, dicts, bytes …) -> ``"[REDACTED]"``.

    Only the first *max_keys* keys are included to prevent log-flooding.
    """
    if not isinstance(args, dict):
        return {"_redacted": True}

    out: dict = {}
    for key in list(args.keys())[:max_keys]:
        lower_key = str(key).lower()
        val = args[key]

        if lower_key in _SENSITIVE_ARG_KEYS:
            out[key] = "[REDACTED]"
        elif isinstance(val, _SAFE_SCALAR_TYPES):
            out[key] = val
        elif lower_key in _SAFE_ARG_KEYS and isinstance(val, str) and len(val) <= _MAX_SAFE_STRING_LEN:
            out[key] = val
        else:
            out[key] = "[REDACTED]"

    if len(args) > max_keys:
        out["_truncated"] = f"{len(args) - max_keys} more key(s) omitted"
    return out
