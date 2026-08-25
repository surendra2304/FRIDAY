# -*- coding: utf-8 -*-
"""Email Drafting & Delivery Workflow for Phase 30.

Orchestrates voice/text email drafting using the FallbackChainLLMProvider,
presents the draft to the user with a confirmation prompt ("Would you like me to send this?"),
and prepares the SENSITIVE send_email tool call.
"""

from typing import Any, Dict, Optional
import re

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.tools.builtin.email_tools import SendEmailTool

logger = get_logger("workflows.email_workflow")


class EmailDraftingWorkflow:
    """Orchestrates LLM-powered email generation, preview, and confirmation prompts."""

    def __init__(self, send_tool: Optional[SendEmailTool] = None) -> None:
        self.send_tool = send_tool or SendEmailTool()

    def can_handle(self, user_prompt: str) -> bool:
        """Check if user prompt is a request to draft an email."""
        if not user_prompt:
            return False
        pattern = r"\b(?:draft|write|compose|prepare)\s+(?:an?\s+)?email\s+(?:to\s+(?P<recipient>[^,\.\n]+?))?\s+(?:about|regarding|for|with\s+subject)\s+(?P<topic>.+)"
        return bool(re.search(pattern, user_prompt, re.IGNORECASE))

    def extract_draft_intent(self, user_prompt: str) -> Dict[str, str]:
        """Parse recipient and subject/topic from the user's drafting request."""
        pattern = r"\b(?:draft|write|compose|prepare)\s+(?:an?\s+)?email\s+(?:to\s+(?P<recipient>[^,\.\n]+?))?\s+(?:about|regarding|for|with\s+subject)\s+(?P<topic>.+)"
        match = re.search(pattern, user_prompt, re.IGNORECASE)
        recipient = ""
        topic = ""
        if match:
            recipient = (match.group("recipient") or "").strip()
            topic = (match.group("topic") or "").strip()
        else:
            # Fallback extraction
            recipient = "Recipient"
            topic = user_prompt

        return {"recipient": recipient, "topic": topic}

    async def draft_email(self, user_prompt: str) -> Dict[str, Any]:
        """Generate email subject and body using the LLM and return structured draft."""
        parsed = self.extract_draft_intent(user_prompt)
        recipient = parsed["recipient"]
        topic = parsed["topic"]

        prompt = (
            "You are FRIDAY's Executive Email Drafting Engine.\n"
            f"Draft a professional, clear, and courteous email to '{recipient or 'the recipient'}' "
            f"regarding: '{topic}'.\n\n"
            "Format your output strictly as follows:\n"
            "Subject: <Subject Line>\n\n"
            "<Body Content>"
        )

        messages = [
            Message(role=Role.SYSTEM, content="You are a professional executive email assistant. Output Subject: followed by the email body."),
            Message(role=Role.USER, content=prompt),
        ]

        subject = f"Update regarding {topic}"
        body = f"Hi {recipient},\n\nI am writing to provide an update on {topic}.\n\nBest regards,\nSurendra"

        try:
            settings = get_settings()
            from friday.llm.factory import create_llm_provider
            provider = create_llm_provider(settings)
            resp = provider.generate(messages=messages)
            text = (resp.content or "").strip()

            if "Subject:" in text:
                parts = text.split("Subject:", 1)[1].strip()
                if "\n" in parts:
                    sub_line, rest = parts.split("\n", 1)
                    subject = sub_line.strip()
                    body = rest.strip()
                else:
                    subject = parts
            else:
                body = text
        except Exception as e:
            logger.warning(f"LLM drafting failed, using clean structured fallback: {e}")

        preview_text = (
            f"Here is the draft email to {recipient}:\n\n"
            f"Subject: {subject}\n\n"
            f"{body}\n\n"
            "Would you like me to send this?"
        )

        return {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "preview_text": preview_text,
        }
