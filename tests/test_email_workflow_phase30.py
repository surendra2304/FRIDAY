# -*- coding: utf-8 -*-
"""Unit tests for Email Tools & Email Drafting Workflow (Web Research & Email Automation)."""

import smtplib
from unittest import mock
import pytest

from friday.core.types import Message, Role, SafetyLevel
from friday.tools.builtin.email_tools import SendEmailTool, _send_smtp_email
from friday.workflows.email_workflow import EmailDraftingWorkflow


def test_send_email_tool_safety_and_name():
    """SendEmailTool must be marked as SENSITIVE."""
    tool = SendEmailTool()
    assert tool.safety_level == SafetyLevel.SENSITIVE
    assert tool.name == "send_email"


def test_send_email_success():
    """SendEmailTool successfully connects to SMTP and delivers email."""
    tool = SendEmailTool()

    with mock.patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = mock.MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with mock.patch("friday.tools.builtin.email_tools.get_settings") as mock_set:
            mock_set.return_value = mock.MagicMock(
                email_address="friday@example.com",
                email_app_password="app_password_123",
                email_smtp_host="smtp.gmail.com",
                email_smtp_port=587,
            )

            res = tool.execute(
                to_address="john@example.com",
                subject="Project Update",
                body="Here is the project update.",
            )

            assert not res.is_error
            assert "Email successfully sent to john@example.com." in res.content
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("friday@example.com", "app_password_123")
            mock_server.sendmail.assert_called_once()


def test_send_email_missing_credentials():
    """SendEmailTool returns clear error when credentials are not configured."""
    tool = SendEmailTool()
    with mock.patch("friday.tools.builtin.email_tools.get_settings") as mock_set:
        mock_set.return_value = mock.MagicMock(
            email_address=None,
            email_app_password=None,
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            res = tool.execute(
                to_address="john@example.com",
                subject="Test",
                body="Body",
            )
            assert res.is_error
            assert "Email sender credentials not configured" in res.content


def test_send_email_authentication_failure():
    """SendEmailTool handles SMTP authentication error gracefully."""
    tool = SendEmailTool()
    with mock.patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = mock.MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        with mock.patch("friday.tools.builtin.email_tools.get_settings") as mock_set:
            mock_set.return_value = mock.MagicMock(
                email_address="friday@example.com",
                email_app_password="bad_password",
                email_smtp_host="smtp.gmail.com",
                email_smtp_port=587,
            )

            res = tool.execute(
                to_address="john@example.com",
                subject="Test",
                body="Body",
            )
            assert res.is_error
            assert "SMTP Authentication failed" in res.content


def test_email_drafting_workflow():
    """EmailDraftingWorkflow parses intent, generates draft via LLM, and asks for confirmation."""
    import asyncio

    workflow = EmailDraftingWorkflow()
    assert workflow.can_handle("Draft an email to John about the project update")
    assert workflow.can_handle("Write an email to Alice regarding tomorrow's meeting")

    mock_llm = mock.MagicMock()
    mock_llm.generate.return_value = Message(
        role=Role.ASSISTANT,
        content="Subject: Project Alpha Update\n\nHi John,\n\nWe have made substantial progress on Web Research & Email Automation.\n\nBest,\nSurendra",
    )

    with mock.patch("friday.llm.factory.create_llm_provider", return_value=mock_llm):
        draft = asyncio.run(workflow.draft_email("Draft an email to John about the project update"))
        assert draft["recipient"] == "John"
        assert draft["subject"] == "Project Alpha Update"
        assert "substantial progress on Web Research & Email Automation" in draft["body"]
        assert "Would you like me to send this?" in draft["preview_text"]
