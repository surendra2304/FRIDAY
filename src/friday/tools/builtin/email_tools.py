"""Email Tools for drafting and sending emails via SMTP.

Provides tools for sending emails with SENSITIVE authorization gating using
Python's built-in smtplib and email.mime packages.
"""

import email.mime.multipart
import email.mime.text
import os
import smtplib
from typing import Any, Sequence

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.email")

_SMTP_TIMEOUT = 12.0


def _recipients_from(to_address: "str | Sequence[str]") -> list[str]:
    """One address or several, blank and duplicate entries dropped."""
    candidates = [to_address] if isinstance(to_address, str) else list(to_address)
    ordered: list[str] = []
    for raw in candidates:
        addr = (raw or "").strip()
        if addr and addr not in ordered:
            ordered.append(addr)
    return ordered


def _describe_refusals(
    recipients: Sequence[str], refused: "dict[str, tuple[int, bytes]]"
) -> str:
    """Report a partial send as the refusal it is.

    ``sendmail`` raises only when *every* recipient is refused. A partial
    refusal comes back as a dict and no exception at all, so ignoring the
    return value is how a message the server rejected came to be reported as
    delivered.
    """
    accepted = [addr for addr in recipients if addr not in refused]
    parts = []
    for addr, detail in refused.items():
        code = detail[0] if isinstance(detail, tuple) and detail else "?"
        text = ""
        if isinstance(detail, tuple) and len(detail) > 1 and detail[1]:
            raw = detail[1]
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        parts.append(f"{addr} (SMTP {code}{': ' + text if text else ''})")
    summary = "; ".join(parts)
    if accepted:
        return (
            f"NOT sent to every recipient. The server refused {summary}. "
            f"Delivered to: {', '.join(accepted)}."
        )
    return f"NOT sent. The server refused every recipient: {summary}."


def _send_smtp_email(
    to_address: "str | Sequence[str]",
    subject: str,
    body: str,
    from_address: str | None = None,
    app_password: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
) -> tuple[bool, str]:
    """Connect to SMTP server and send MIME text email.

    Returns True only when the server accepted every recipient. A recipient it
    refused is never reported as sent, whether the refusal arrived as an
    exception or as ``sendmail``'s return value.
    """
    settings = get_settings()
    sender = from_address or getattr(settings, "email_address", None) or os.getenv("FRIDAY_EMAIL_ADDRESS")
    password = app_password or getattr(settings, "email_app_password", None) or os.getenv("FRIDAY_EMAIL_APP_PASSWORD")
    host = smtp_host or getattr(settings, "email_smtp_host", "smtp.gmail.com") or os.getenv("FRIDAY_EMAIL_SMTP_HOST", "smtp.gmail.com")
    port = smtp_port or getattr(settings, "email_smtp_port", 587) or int(os.getenv("FRIDAY_EMAIL_SMTP_PORT", 587))

    if not sender or not password:
        return False, "Email sender credentials not configured. Please set FRIDAY_EMAIL_ADDRESS and FRIDAY_EMAIL_APP_PASSWORD in your .env file."

    recipients = _recipients_from(to_address)
    if not recipients:
        return False, "No recipient address was given, so there was nothing to send."

    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, password)
            refused = server.sendmail(sender, recipients, msg.as_string())
        # A refusal the server already reported is still a refusal. This is the
        # only place a send is called sent, so it is the only place that has to
        # know sendmail answers with a dict rather than raising. Keyed on the
        # mapping type because that is the contract, not on truthiness.
        if isinstance(refused, dict) and refused:
            reason = _describe_refusals(recipients, refused)
            logger.warning(f"SMTP refused a recipient for '{subject}': {reason}")
            return False, reason
        logger.info(f"Email sent successfully to '{to_address}' with subject '{subject}'.")
        return True, f"Email successfully sent to {', '.join(recipients)}."
    except smtplib.SMTPAuthenticationError as e:
        logger.warning(f"SMTP authentication failed: {e}")
        return False, f"SMTP Authentication failed: Invalid email or app password. ({e})"
    except smtplib.SMTPConnectError as e:
        logger.warning(f"SMTP connection error: {e}")
        return False, f"Could not connect to SMTP server '{host}:{port}': {e}"
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False, f"Failed to send email to {to_address}: {e!s}"


class SendEmailTool(BaseTool):
    """Send an email via SMTP. Marked SENSITIVE to enforce user authorization."""

    name = "send_email"
    description = (
        "Send an email to a recipient with a subject line and body. "
        "Requires authorization as a SENSITIVE action."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "to_address": {
                "type": "string",
                "description": "Recipient email address (e.g. 'john@example.com').",
            },
            "subject": {
                "type": "string",
                "description": "The email subject line.",
            },
            "body": {
                "type": "string",
                "description": "The plain text body content of the email.",
            },
        },
        "required": ["to_address", "subject", "body"],
    }

    def execute(self, to_address: str, subject: str, body: str, **kwargs: Any) -> ToolResult:
        recipient = (to_address or "").strip()
        subj = (subject or "").strip()
        content = (body or "").strip()

        if not recipient:
            return ToolResult(
                name=self.name,
                content="Error: Recipient email address ('to_address') is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not subj:
            return ToolResult(
                name=self.name,
                content="Error: Email subject line is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        if not content:
            return ToolResult(
                name=self.name,
                content="Error: Email body content is required.",
                is_error=True,
                safety_level=self.safety_level,
            )

        ok, msg = _send_smtp_email(to_address=recipient, subject=subj, body=content)
        return ToolResult(
            name=self.name,
            content=msg,
            is_error=not ok,
            safety_level=self.safety_level,
        )


class DraftEmailTool(BaseTool):
    """Draft an email for user review and confirmation before sending."""

    name = "draft_email"
    description = (
        "Draft an email message with recipient, subject, and body for user review. "
        "Safe to call without sending. Returns the formatted draft."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "to_address": {
                "type": "string",
                "description": "Recipient name or email address.",
            },
            "subject": {
                "type": "string",
                "description": "The proposed email subject line.",
            },
            "body": {
                "type": "string",
                "description": "The proposed body text of the email.",
            },
        },
        "required": ["to_address", "subject", "body"],
    }

    def execute(self, to_address: str, subject: str, body: str, **kwargs: Any) -> ToolResult:
        recipient = (to_address or "").strip()
        subj = (subject or "").strip()
        content = (body or "").strip()

        draft = (
            f"--- EMAIL DRAFT ---\n"
            f"To: {recipient}\n"
            f"Subject: {subj}\n\n"
            f"{content}\n"
            f"-------------------\n"
            f"Draft created. Ready to send upon user confirmation."
        )

        return ToolResult(
            name=self.name,
            content=draft,
            is_error=False,
            safety_level=self.safety_level,
        )
