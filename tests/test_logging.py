"""Tests for logging and secret sanitization."""

import logging
from friday.core.logging import SecretMaskingFilter, get_logger, setup_logging


def test_secret_masking_filter_direct_secret():
    secret = "my-super-secret-token-12345"
    f = SecretMaskingFilter(secrets_to_mask=[secret])
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"Using credentials {secret} to connect",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert secret not in record.msg
    assert "***" in record.msg


def test_secret_masking_filter_regex_keys():
    f = SecretMaskingFilter()
    sample_key = "sk-abcdef1234567890abcdef123456"
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"API key loaded: {sample_key}",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert sample_key not in record.msg


def test_get_logger_namespace():
    log = get_logger("custom_subsystem")
    assert log.name == "friday.custom_subsystem"


def test_setup_logging(tmp_path):
    log_file = tmp_path / "test_friday.log"
    logger = setup_logging(level="DEBUG", log_file=str(log_file))
    logger.info("Test log message")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test log message" in content
