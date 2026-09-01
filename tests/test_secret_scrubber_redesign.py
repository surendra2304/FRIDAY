"""Unit and integration tests for the unified Secret Scrubber redesign."""

import logging
import sqlite3

from friday.core.exceptions import FridayError
from friday.core.types import Message, Role, SafetyLevel, ToolResult
from friday.memory.sqlite import SQLiteConversationMemory
from friday.security.scrubber import global_scrubber, redact_secrets

# Direct test vectors for different credential formats
SECRET_TEST_CASES = [
    # Google API / Gemini key
    ("AIzaSyB1a2MzZDRlNWY2Zzc4OTBhYmNkZWZnaGk", "[REDACTED_SECRET]"),
    # OpenAI API key
    ("sk-proj-1234567890abcdef1234567890abcdef12345678", "[REDACTED_SECRET]"),
    # Bearer token
    ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "[REDACTED_SECRET]"),
    # JWT token (standalone)
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "[REDACTED_SECRET]"),
    # AWS Access Key ID
    ("AKIAIOSFODNN7EXAMPLE", "[REDACTED_SECRET]"),
    # Database connection string with inline credentials
    ("postgresql://postgres:secret_password_123@localhost:5432/production_db", "[REDACTED_SECRET]"),
    # Cookies header
    ("Cookie: session_id=abc123xyz789; oauth_token=9988776655", "Cookie: [REDACTED_SECRET]"),
    # Authorization header
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: [REDACTED_SECRET]"),
    # Inline key-value password
    ("password = super_secure_pass_99", "password: [REDACTED_SECRET]"),
]


def test_direct_pattern_redaction():
    """Verify that redact_secrets successfully masks all standard credential formats."""
    for secret, expected in SECRET_TEST_CASES:
        res = redact_secrets(secret)
        assert secret not in res, f"Failed to redact: {secret} (Got: {res})"


def test_configured_credential_exact_masking():
    """Verify that exact configured settings/credentials registered with scrubber are masked."""
    exact_credential = "my-super-secret-custom-key-109283"
    global_scrubber.register_secret(exact_credential)

    text = f"Received key {exact_credential} from LLM provider."
    res = redact_secrets(text)
    assert exact_credential not in res
    assert "[REDACTED]" in res


def test_exception_secret_scrubbing():
    """Verify that raising or printing FridayError automatically redacts credentials."""
    gemini_key = "AIzaSyB1a2MzZDRlNWY2Zzc4OTBhYmNkZWZnaGk"
    try:
        raise FridayError(f"Failed connection using key {gemini_key}")
    except FridayError as e:
        msg = str(e)
        assert gemini_key not in msg
        assert "[REDACTED_SECRET]" in msg


def test_tool_result_sanitization():
    """Verify that ToolResult models automatically scrub credentials on creation."""
    db_conn = "postgresql://postgres:secret_password_123@localhost:5432/production_db"
    res = ToolResult(
        tool_call_id="call_test",
        name="run_query",
        content=f"Database connected at {db_conn}",
        safety_level=SafetyLevel.SAFE,
    )
    assert db_conn not in res.content
    assert "[REDACTED_SECRET]" in res.content


def test_message_content_sanitization():
    """Verify that Message models automatically scrub credentials on creation."""
    openai_key = "sk-proj-1234567890abcdef1234567890abcdef12345678"
    msg = Message(
        role=Role.USER,
        content=f"Use key {openai_key} to proceed.",
    )
    assert openai_key not in msg.content
    assert "[REDACTED_SECRET]" in msg.content


def test_sqlite_memory_scrubbing(tmp_path):
    """Verify that database persistence automatically sanitizes secrets before storage."""
    db_file = tmp_path / "test_scrub.db"
    mem = SQLiteConversationMemory(db_path=str(db_file), embedding_provider=None)
    conv_id = mem.create_conversation("Auth Test")

    aws_secret = "AKIAIOSFODNN7EXAMPLE"
    msg = Message(role=Role.USER, content=f"My AWS key is {aws_secret}")
    mem.add_message(msg, conv_id)

    # Read back from database using a raw connection to ensure the persisted text is clean
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT content FROM messages WHERE conversation_id = ?", (conv_id,)).fetchone()
    conn.close()

    assert row is not None
    persisted_content = row["content"]
    assert aws_secret not in persisted_content
    assert "[REDACTED_SECRET]" in persisted_content


def test_logging_filter_scrubbing():
    """Verify that logging output is intercepted and sanitized."""
    from friday.core.logging import SecretMaskingFilter
    mask_filter = SecretMaskingFilter()

    secret_key = "sk-proj-1234567890abcdef1234567890abcdef12345678"
    record = logging.LogRecord(
        name="friday.test_scrub",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg=f"Initializing provider with key: {secret_key}",
        args=(),
        exc_info=None,
    )

    assert mask_filter.filter(record) is True
    assert secret_key not in record.msg
    assert "[REDACTED_SECRET]" in record.msg
