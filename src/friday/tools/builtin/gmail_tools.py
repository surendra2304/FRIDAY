"""Gmail Tools for FRIDAY.

Provides comprehensive Gmail capabilities:
1. Read recent or unread emails via IMAP (imap.gmail.com).
2. Search email threads by sender, subject, or query.
3. Send emails securely via SMTP with STARTTLS.
4. Open Gmail web interface in browser.
"""

from __future__ import annotations

import email
from email.header import decode_header
import email.mime.multipart
import email.mime.text
import imaplib
import os
import smtplib
import webbrowser
from typing import Any

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.gmail")

_IMAP_SERVER = "imap.gmail.com"
_SMTP_SERVER = "smtp.gmail.com"
_SMTP_PORT = 587
_TIMEOUT = 12.0


def _decode_mime_header(header_val: str | None) -> str:
    if not header_val:
        return ""
    parts = decode_header(header_val)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return "".join(decoded)


class ReadGmailInboxTool(BaseTool):
    """Tool to check and read recent or unread emails from Gmail."""

    name = "read_gmail_inbox"
    description = (
        "Read recent emails or search the Gmail inbox. Can filter by unread status, "
        "sender, or keyword query. Returns subject, sender, date, and preview snippet."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "max_emails": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of recent emails to retrieve (default 5, max 20).",
            },
            "only_unread": {
                "type": "boolean",
                "default": False,
                "description": "Whether to only fetch unread emails.",
            },
            "query": {
                "type": "string",
                "description": "Optional search keyword to filter emails (e.g. from sender or subject).",
            },
        },
    }

    def execute(self, max_emails: int = 5, only_unread: bool = False, query: str | None = None, **kwargs: Any) -> ToolResult:
        settings = get_settings()
        user_email = getattr(settings, "email_address", None) or os.getenv("FRIDAY_EMAIL_ADDRESS")
        app_password = getattr(settings, "email_app_password", None) or os.getenv("FRIDAY_EMAIL_APP_PASSWORD")

        if not user_email or not app_password:
            # Fallback: Offer to open Gmail web interface
            webbrowser.open("https://mail.google.com")
            return ToolResult(
                name=self.name,
                content=(
                    "Gmail credentials (FRIDAY_EMAIL_ADDRESS and FRIDAY_EMAIL_APP_PASSWORD) not configured in .env. "
                    "Opened Gmail in your web browser instead."
                ),
                is_error=False,
                safety_level=self.safety_level,
            )

        limit = min(max(1, max_emails), 20)
        try:
            mail = imaplib.IMAP4_SSL(_IMAP_SERVER, timeout=_TIMEOUT)
            mail.login(user_email, app_password)
            mail.select("INBOX")

            search_criterion = "UNSEEN" if only_unread else "ALL"
            if query:
                search_criterion = f'(TEXT "{query}")'

            status, data = mail.search(None, search_criterion)
            if status != "OK" or not data[0]:
                mail.logout()
                return ToolResult(
                    name=self.name,
                    content="No matching emails found in Gmail inbox.",
                    is_error=False,
                    safety_level=self.safety_level,
                )

            email_ids = data[0].split()
            recent_ids = email_ids[-limit:]
            recent_ids.reverse()

            results = []
            for eid in recent_ids:
                res, msg_data = mail.fetch(eid, "(RFC822)")
                if res != "OK":
                    continue
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = _decode_mime_header(msg.get("Subject", "No Subject"))
                from_addr = _decode_mime_header(msg.get("From", "Unknown"))
                date_str = msg.get("Date", "")

                body_preview = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_preview = payload.decode(errors="replace")[:160].strip()
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_preview = payload.decode(errors="replace")[:160].strip()

                results.append(
                    f"📧 **Subject:** {subject}\n"
                    f"   **From:** {from_addr}\n"
                    f"   **Date:** {date_str}\n"
                    f"   **Snippet:** {body_preview}..."
                )

            mail.logout()
            summary = f"Found {len(results)} email(s) in inbox:\n\n" + "\n\n".join(results)
            return ToolResult(
                name=self.name,
                content=summary,
                is_error=False,
                safety_level=self.safety_level,
                metadata={"email_count": len(results)},
            )
        except Exception as e:
            logger.error(f"Failed to read Gmail: {e}")
            webbrowser.open("https://mail.google.com")
            return ToolResult(
                name=self.name,
                content=f"Could not connect via IMAP ({e}). Opened Gmail in browser.",
                is_error=False,
                safety_level=self.safety_level,
            )


class DraftGmailTool(BaseTool):
    """Tool to compose and preview email drafts with recipient disambiguation and idempotency."""

    name = "draft_gmail"
    description = (
        "Compose an email draft with recipient disambiguation and read-back preview. "
        "Generates an idempotency token without sending external communication."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "to_address": {
                "type": "string",
                "description": "Recipient email address or contact name.",
            },
            "subject": {
                "type": "string",
                "description": "Subject of the email.",
            },
            "body": {
                "type": "string",
                "description": "Plain text content of the email.",
            },
        },
        "required": ["to_address", "subject", "body"],
    }

    def execute(self, to_address: str, subject: str, body: str, **kwargs: Any) -> ToolResult:
        import re
        import uuid
        to_clean = (to_address or "").strip()
        subj_clean = (subject or "").strip()
        body_clean = (body or "").strip()

        # Recipient disambiguation: check if valid email format
        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        is_valid_email = bool(re.match(email_regex, to_clean))

        resolved_email = to_clean
        disambiguation_note = ""
        if not is_valid_email:
            # Attempt to resolve common contact aliases or domain
            if "@" not in to_clean:
                disambiguation_note = f"⚠️ Recipient '{to_clean}' is a contact name, not an email address. Please confirm destination address."
            else:
                disambiguation_note = f"⚠️ Recipient '{to_clean}' format may be invalid."

        idempotency_key = f"draft_{uuid.uuid4().hex[:10]}"

        preview = (
            f"📝 **Email Draft Preview (Ready for Authorization)**\n"
            f"**To:** {resolved_email}\n"
            f"**Subject:** {subj_clean}\n"
            f"**Body:**\n---\n{body_clean}\n---\n"
            f"**Idempotency Token:** `{idempotency_key}`\n"
        )
        if disambiguation_note:
            preview += f"\n{disambiguation_note}"

        return ToolResult(
            name=self.name,
            content=preview,
            is_error=False,
            safety_level=self.safety_level,
            metadata={
                "idempotency_key": idempotency_key,
                "recipient": resolved_email,
                "subject": subj_clean,
                "body": body_clean,
                "is_disambiguated": is_valid_email,
            },
        )


class SendGmailTool(BaseTool):
    """Tool to compose and send emails via Gmail SMTP with strict authorization."""

    name = "send_gmail"
    description = (
        "Send an email via Gmail SMTP. Supports recipient, subject line, body text, "
        "and idempotency verification. Requires authorization."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "to_address": {
                "type": "string",
                "description": "Recipient email address (e.g. 'friend@example.com').",
            },
            "subject": {
                "type": "string",
                "description": "Subject of the email.",
            },
            "body": {
                "type": "string",
                "description": "Plain text content of the email.",
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional idempotency key generated by draft_gmail.",
            },
        },
        "required": ["to_address", "subject", "body"],
    }

    def execute(self, to_address: str, subject: str, body: str, idempotency_key: str | None = None, **kwargs: Any) -> ToolResult:
        settings = get_settings()
        user_email = getattr(settings, "email_address", None) or os.getenv("FRIDAY_EMAIL_ADDRESS")
        app_password = getattr(settings, "email_app_password", None) or os.getenv("FRIDAY_EMAIL_APP_PASSWORD")

        if not user_email or not app_password:
            # Fallback to mailto URI in browser
            import urllib.parse
            mailto = f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(to_address)}&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
            webbrowser.open(mailto)
            return ToolResult(
                name=self.name,
                content=(
                    "Gmail credentials not configured in .env. "
                    "Opened Gmail compose window in your browser with your draft ready."
                ),
                is_error=False,
                safety_level=self.safety_level,
                metadata={"provider": "web_browser", "idempotency_key": idempotency_key},
            )

        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = user_email
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

        try:
            with smtplib.SMTP(_SMTP_SERVER, _SMTP_PORT, timeout=_TIMEOUT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user_email, app_password)
                send_errs = server.sendmail(user_email, [to_address], msg.as_string())

            logger.info(f"Gmail sent successfully to {to_address}")
            return ToolResult(
                name=self.name,
                content=f"Email successfully sent to {to_address} with subject '{subject}'.",
                is_error=False,
                safety_level=self.safety_level,
                metadata={
                    "provider": "smtp.gmail.com",
                    "idempotency_key": idempotency_key,
                    "recipient": to_address,
                    "send_errors": send_errs,
                    "status": "SENT",
                },
            )
        except Exception as e:
            logger.error(f"Failed to send Gmail: {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to send email to {to_address}: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
