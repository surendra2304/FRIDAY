"""Unit tests for multi-turn confirmation context, Memora recording, and extended laptop directives."""

import pytest
from unittest import mock

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import Message, Role, AgentResponse
from friday.devices.windows_friday import windows_friday
from friday.agent.goal import GoalUnderstandingEngine, GoalRequestType
from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase


def test_goal_understanding_affirmations():
    """Verify that affirmations and negations are not flagged as ambiguous in GoalUnderstandingEngine."""
    engine = GoalUnderstandingEngine()
    for token in ["yes", "y", "sure", "ok", "okay", "proceed", "send", "send it", "confirm", "do it"]:
        goal = engine.analyze_goal(token)
        assert goal.request_type != GoalRequestType.AMBIGUOUS_REQUEST, f"Failed for '{token}'"
        assert not goal.is_ambiguous

    for token in ["no", "n", "cancel", "stop", "abort", "don't", "never mind"]:
        goal = engine.analyze_goal(token)
        assert goal.request_type != GoalRequestType.AMBIGUOUS_REQUEST, f"Failed for '{token}'"
        assert not goal.is_ambiguous


def test_cognitive_engine_affirmation_evaluation():
    """Verify CognitiveIntelligenceEngine does not trigger CLARIFY for affirmations/negations."""
    engine = CognitiveIntelligenceEngine()
    for token in ["yes", "y", "sure", "ok", "proceed", "no", "cancel"]:
        decision = engine.evaluate_request(token)
        assert decision.current_phase != CognitivePhase.CLARIFY, f"Failed for '{token}'"
        assert not decision.lacks_information


def test_multiturn_email_confirmation():
    """Verify multi-turn confirmation: drafting an email followed by 'yes' resolves to action execution."""
    settings = Settings(
        api_key="test-key",
        user_name="Surendra",
        persona="friday",
    )
    agent = FridayAgent(settings=settings)

    # Simulate Turn 1: Assistant drafted an email and asked for confirmation
    draft_msg = (
        "--- EMAIL DRAFT ---\n"
        "To: john@example.com\n"
        "Subject: Project Alpha Launch\n\n"
        "Hi John, all systems are operational.\n"
        "-------------------\n"
        "Would you like me to send this?"
    )
    agent.memory.add_message(Message(role=Role.USER, content="draft an email to john@example.com about Project Alpha Launch"))
    agent.memory.add_message(Message(role=Role.ASSISTANT, content=draft_msg))

    with mock.patch.object(agent, "execute_complex_task") as mock_exec:
        mock_exec.return_value = AgentResponse(
            content="Email successfully sent to john@example.com.",
            is_done=True,
            metadata={"is_successful": True},
        )

        resp = agent.process_message("yes")

        assert resp.content != "Could you please specify which file, application, or action you would like me to process? ('yes' is ambiguous)."
        assert "Email successfully sent" in resp.content
        mock_exec.assert_called_once()
        called_goal = mock_exec.call_args[1].get("goal") or mock_exec.call_args[0][0]
        assert "john@example.com" in called_goal
        assert "Project Alpha Launch" in called_goal


def test_multiturn_action_cancellation():
    """Verify multi-turn negation: saying 'no' or 'cancel' cancels the pending prompt instantly."""
    settings = Settings(
        api_key="test-key",
        user_name="Surendra",
        persona="friday",
    )
    agent = FridayAgent(settings=settings)

    draft_msg = (
        "Here is the draft email to client@example.com:\n\n"
        "Subject: Follow up\n\n"
        "Would you like me to send this?"
    )
    agent.memory.add_message(Message(role=Role.USER, content="draft an email to client@example.com"))
    agent.memory.add_message(Message(role=Role.ASSISTANT, content=draft_msg))

    with mock.patch.object(agent, "execute_complex_task") as mock_exec:
        resp = agent.process_message("no")

        assert "cancelled" in resp.content.lower()
        mock_exec.assert_not_called()


def test_windows_friday_extended_volume_directives():
    """Verify WindowsFridayController handles expanded volume percentages."""
    with mock.patch.object(windows_friday, "set_volume_percent", return_value=(True, "Volume set to 65%.")) as mock_vol:
        handled, reply, meta = windows_friday.handle_directive("increase the volume to 65%")
        assert handled
        assert meta["action"] == "set_volume"
        assert meta["percent"] == 65

    with mock.patch.object(windows_friday, "set_volume_percent", return_value=(True, "Volume set to 80%.")) as mock_vol:
        handled, reply, meta = windows_friday.handle_directive("raise volume to 80%")
        assert handled
        assert meta["percent"] == 80

    with mock.patch.object(windows_friday, "volume_up", return_value="Volume increased.") as mock_up:
        handled, reply, meta = windows_friday.handle_directive("raise the volume")
        assert handled
        assert meta["action"] == "volume_up"


def test_windows_friday_gmail_and_whatsapp_directives():
    """Verify WindowsFridayController handles Gmail and WhatsApp directives."""
    with mock.patch.object(windows_friday, "open_gmail", return_value=(True, "Opened Gmail.")) as mock_gmail:
        handled, reply, meta = windows_friday.handle_directive("open gmail")
        assert handled
        assert meta["action"] == "open_gmail"

    with mock.patch.object(windows_friday, "open_gmail", return_value=(True, "Opened Gmail.")) as mock_gmail:
        handled, reply, meta = windows_friday.handle_directive("compose email to test@example.com about Meeting")
        assert handled
        assert meta["action"] == "open_gmail"
        assert meta["to"] == "test@example.com"

    with mock.patch.object(windows_friday, "open_whatsapp", return_value=(True, "Opened WhatsApp Web.")) as mock_wa:
        handled, reply, meta = windows_friday.handle_directive("open whatsapp")
        assert handled
        assert meta["action"] == "open_whatsapp"

    with mock.patch.object(windows_friday, "open_whatsapp", return_value=(True, "Opened WhatsApp Web.")) as mock_wa:
        handled, reply, meta = windows_friday.handle_directive("send whatsapp to 1234567890 saying hello there")
        assert handled
        assert meta["action"] == "open_whatsapp"
        assert meta["phone"] == "1234567890"
