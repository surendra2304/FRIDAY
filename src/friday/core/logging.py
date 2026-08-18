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
        self.secrets = [s for s in (secrets_to_mask or []) if s and len(s) > 4]
        # Regex patterns for common secret formats (e.g. sk-..., bearer tokens)
        self.patterns = [
            re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
            re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
            re.compile(r"(api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?([^'\"\s]+)['\"]?", re.IGNORECASE),
        ]

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
        # Mask explicitly known secrets
        for secret in self.secrets:
            if secret in text:
                text = text.replace(secret, "***")

        # Mask regex matching secrets
        for pattern in self.patterns:
            text = pattern.sub(r"\1: [REDACTED]", text) if "api" in pattern.pattern else pattern.sub("[REDACTED_SECRET]", text)
        return text


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Initialize root and application loggers with sanitization."""
    settings = get_settings()
    log_level_str = level or settings.log_level
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    target_file = log_file or settings.log_file

    logger = logging.getLogger("friday")
    logger.setLevel(log_level)

    # Avoid duplicate handlers if setup is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    mask_filter = SecretMaskingFilter(
        secrets_to_mask=[settings.llm_api_key] if settings.llm_api_key else []
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(mask_filter)
    logger.addHandler(console_handler)

    # File Handler
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
