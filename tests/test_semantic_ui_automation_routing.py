"""Mock tests for semantic UI-action routing: IntentDetector -> pywinauto provider -> agent."""

from types import SimpleNamespace
from unittest import mock

import pytest

from friday.core.types import AuthorizationDecision, AuthorizationResponse
from friday.vision.intent_detector import ActionIntent, IntentDetector


# ---------------------------------------------------------------------------
# IntentDetector patterns
# ---------------------------------------------------------------------------


def test_generic_click_button_pattern():
    result = IntentDetector.detect("click the send button")
    assert result.intent == ActionIntent.SEMANTIC_UI_ACTION
    assert result.confidence == 1.0
    assert result.parsed_data["action_type"] == "click"
    assert result.parsed_data["target"] == "send"


def test_generic_click_tab_menu_link_patterns():
    for phrase, target in [
        ("click the General tab", "general"),
        ("click the File menu", "file"),
        ("submit link", None),  # not a click phrase -> OTHER unless matched elsewhere
    ]:
        result = IntentDetector.detect(phrase)
        if target is None:
            assert result.intent == ActionIntent.OTHER
        else:
            assert result.intent == ActionIntent.SEMANTIC_UI_ACTION
            assert result.parsed_data["target"] == target


def test_open_notepad_detected_as_launch():
    result = IntentDetector.detect("open notepad")
    assert result.intent == ActionIntent.SEMANTIC_UI_ACTION
    assert result.confidence == 1.0
    assert result.parsed_data["action_type"] == "launch"
    assert result.parsed_data["target"] == "notepad"
    assert result.parsed_data["executable"] == "notepad.exe"


def test_launch_calculator_variants():
    for phrase in ["launch calculator", "start paint", "run notepad", "please open the calculator"]:
        result = IntentDetector.detect(phrase)
        assert result.intent == ActionIntent.SEMANTIC_UI_ACTION, phrase
        assert result.parsed_data["action_type"] == "launch", phrase


def test_unknown_app_open_falls_to_other():
    result = IntentDetector.detect("open spotify")
    assert result.intent == ActionIntent.OTHER


def test_existing_patterns_still_work():
    result = IntentDetector.detect("click the start button")
    assert result.intent == ActionIntent.SEMANTIC_UI_ACTION
    assert result.parsed_data["target"] == "Start"

    result = IntentDetector.detect("press the enter key")
    assert result.parsed_data["action_type"] == "key_press"


def test_geometric_actions_take_priority():
    result = IntentDetector.detect("click at x=100 y=200")
    assert result.intent == ActionIntent.GEOMETRIC_ACTION


# ---------------------------------------------------------------------------
# WindowsUIAutomationProvider.launch_application (native os.startfile / subprocess)
# ---------------------------------------------------------------------------


def _make_uia_provider():
    from friday.ui_automation import provider as uia_module

    return uia_module, uia_module.WindowsUIAutomationProvider.__new__(
        uia_module.WindowsUIAutomationProvider
    )


def test_launch_application_uses_startfile_for_exe(monkeypatch):
    uia_module, provider = _make_uia_provider()
    started = {}

    fake_os = SimpleNamespace(startfile=lambda exe: started.setdefault("exe", exe))
    monkeypatch.setattr(uia_module, "os", fake_os)
    popen_calls = []
    monkeypatch.setattr(
        uia_module, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: popen_calls.append(a))
    )

    assert provider.launch_application("chrome.exe") is True
    assert started["exe"] == "chrome.exe"  # App Paths resolution via ShellExecute
    assert popen_calls == []  # startfile succeeded: no subprocess fallback


def test_launch_application_falls_back_to_subprocess(monkeypatch):
    uia_module, provider = _make_uia_provider()

    def bad_startfile(exe):
        raise OSError("not registered")

    monkeypatch.setattr(uia_module, "os", SimpleNamespace(startfile=bad_startfile))
    popen_calls = []
    monkeypatch.setattr(
        uia_module, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: popen_calls.append(a))
    )

    assert provider.launch_application("someapp.exe") is True
    assert popen_calls == [("someapp.exe",)]


def test_launch_application_protocol_uri_uses_startfile(monkeypatch):
    uia_module, provider = _make_uia_provider()
    started = {}
    monkeypatch.setattr(uia_module, "os", SimpleNamespace(startfile=lambda exe: started.setdefault("uri", exe)))
    monkeypatch.setattr(uia_module, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: None))

    assert provider.launch_application("ms-settings:") is True
    assert started["uri"] == "ms-settings:"


def test_launch_application_total_failure_returns_false(monkeypatch):
    uia_module, provider = _make_uia_provider()
    monkeypatch.setattr(uia_module, "os", SimpleNamespace(startfile=lambda exe: (_ for _ in ()).throw(OSError("no"))))
    monkeypatch.setattr(uia_module, "subprocess", SimpleNamespace(Popen=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no"))))

    assert provider.launch_application("nonexistent.exe") is False


def test_find_element_scores_parts_and_confidence(monkeypatch):
    from friday.ui_automation import provider as uia_module

    provider = uia_module.WindowsUIAutomationProvider.__new__(uia_module.WindowsUIAutomationProvider)
    elements = [
        uia_module.UIElement(
            handle=None,
            automation_id="sendButton",
            name="Send",
            control_type="Button",
            rectangle={"left": 0, "top": 0, "right": 10, "bottom": 10},
        ),
        uia_module.UIElement(
            handle=None,
            automation_id=None,
            name="Address Bar",
            control_type="Edit",
            rectangle={"left": 0, "top": 0, "right": 10, "bottom": 10},
        ),
    ]
    monkeypatch.setattr(provider, "_enumerate_all_elements", lambda: elements)

    found = provider.find_element("send")
    assert found is elements[0]
    assert found.confidence >= 0.85  # substring containment bonus


# ---------------------------------------------------------------------------
# Agent-level routing (bypasses LLM/Vision)
# ---------------------------------------------------------------------------


class FakeUIProvider:
    def __init__(self, element_confidence=0.9, click_ok=True, launch_ok=True):
        self._element_confidence = element_confidence
        self._click_ok = click_ok
        self._launch_ok = launch_ok
        self.launch_calls = []

    def find_element(self, query):
        el = SimpleNamespace(handle=None, confidence=self._element_confidence)
        return el

    def click(self, element):
        return self._click_ok

    def launch_application(self, executable):
        self.launch_calls.append(executable)
        return self._launch_ok


def _make_agent_with(provider, llm):
    """Build a FridayAgent wired with fake UI provider and mock LLM, no side effects."""
    from friday.agent.agent import FridayAgent
    from friday.core.config import Settings
    from friday.memory.in_memory import InMemoryConversationMemory

    settings = Settings(env="testing", llm_provider="mock", ui_automation_enabled=True)
    agent = FridayAgent.__new__(FridayAgent)
    agent.settings = settings
    agent.llm = llm
    agent.memory = InMemoryConversationMemory()
    agent.ui_provider = provider
    agent.tools = mock.MagicMock()
    agent.authorizer = mock.MagicMock()
    agent.authorizer.authorize.return_value = AuthorizationResponse(
        decision=AuthorizationDecision.APPROVED, reason="test"
    )
    agent.capability_router = mock.MagicMock()
    agent.capability_router.route_request.return_value = SimpleNamespace(
        selected_capability=SimpleNamespace(value="TOOL_EXECUTION")
    )
    agent.cognitive_engine = mock.MagicMock()
    agent.max_tool_iterations = 3
    agent.tool_callback = None
    agent.tool_timeout = 5.0
    agent.system_message = mock.MagicMock()
    agent.state_machine = mock.MagicMock()
    agent.task_context = None
    return agent


def test_agent_routes_click_to_uia_bypassing_llm():
    llm = mock.MagicMock()
    agent = _make_agent_with(FakeUIProvider(element_confidence=0.9), llm)
    response = agent._execute_semantic_ui_action(
        IntentDetector.detect("click the send button"), "click the send button"
    )
    assert response is not None
    assert response.metadata["ui_automation"] is True
    assert response.metadata["target"] == "send"
    llm.generate.assert_not_called()


def test_agent_click_below_element_confidence_falls_through():
    agent = _make_agent_with(FakeUIProvider(element_confidence=0.3), mock.MagicMock())
    response = agent._execute_semantic_ui_action(
        IntentDetector.detect("click the send button"), "click the send button"
    )
    assert response is None  # falls through to the normal LLM pipeline


def test_agent_launch_notepad_via_uia():
    provider = FakeUIProvider()
    agent = _make_agent_with(provider, mock.MagicMock())
    response = agent._execute_semantic_ui_action(IntentDetector.detect("open notepad"), "open notepad")
    assert response is not None
    assert response.content == "Opened notepad."
    assert provider.launch_calls == ["notepad.exe"]


def test_agent_launch_shell_app_requires_authorization():
    provider = FakeUIProvider()
    agent = _make_agent_with(provider, mock.MagicMock())
    denied = AuthorizationResponse(decision=AuthorizationDecision.DENIED, reason="sensitive")
    agent.authorizer.authorize.return_value = denied
    response = agent._execute_semantic_ui_action(IntentDetector.detect("open command prompt"), "open command prompt")
    assert response is None  # unauthorized -> fall through
    assert provider.launch_calls == []


def test_agent_launch_failure_falls_through():
    provider = FakeUIProvider(launch_ok=False)
    agent = _make_agent_with(provider, mock.MagicMock())
    response = agent._execute_semantic_ui_action(IntentDetector.detect("open notepad"), "open notepad")
    assert response is None
    assert provider.launch_calls == ["notepad.exe"]


# ---------------------------------------------------------------------------
# Greeting fast-path (bypasses cognitive loop / clarification / tools)
# ---------------------------------------------------------------------------


def test_greeting_fast_path_matches_simple_greetings():
    agent = _make_agent_with(FakeUIProvider(), mock.MagicMock())
    for greeting in ["hi", "Hello", "HEY", "sup?", "hi!", "hey there", "hello!"]:
        response = agent._greeting_fast_path(greeting)
        assert response is not None, greeting
        assert response.is_done is True
        assert response.metadata["greeting_fast_path"] is True
        assert "Surendra" in response.content or "help" in response.content.lower()


def test_greeting_fast_path_rejects_compound_requests():
    agent = _make_agent_with(FakeUIProvider(), mock.MagicMock())
    for phrase in [
        "hey, open notepad",
        "hi can you click the send button",
        "sup, what time is it",
        "hello FRIDAY",  # addressed requests flow through the LLM pipeline
    ]:
        assert agent._greeting_fast_path(phrase) is None, phrase


def test_process_message_greeting_bypasses_cognitive_loop():
    agent = _make_agent_with(FakeUIProvider(), mock.MagicMock())
    response = agent.process_message("hello")
    assert response.is_done is True
    assert response.metadata.get("greeting_fast_path") is True
    agent.cognitive_engine.evaluate_request.assert_not_called()
    agent.capability_router.route_request.assert_not_called()
    # Both turns recorded for multi-turn context
    history = agent.get_history()
    assert len(history) == 2
    assert history[0].role.value == "user"
    assert history[1].role.value == "assistant"


def test_process_message_compound_phrase_still_routes_normally():
    agent = _make_agent_with(FakeUIProvider(), mock.MagicMock())
    response = agent.process_message("hey, open notepad")
    assert response.metadata.get("greeting_fast_path") is None
    agent.cognitive_engine.evaluate_request.assert_called_once()


# ---------------------------------------------------------------------------
# Identity prompt is provider-agnostic
# ---------------------------------------------------------------------------


def test_system_prompt_is_provider_agnostic():
    from friday.agent.prompts import get_default_system_prompt
    from friday.core.config import Settings

    prompt = get_default_system_prompt(Settings())
    assert "multi-provider architecture" in prompt
    for banned in ("Google Gemini", "Gemini", "OpenAI", "Groq", "Cerebras", "OpenRouter", "powered by"):
        assert banned.lower() not in prompt.lower(), f"Found '{banned}' in system prompt"


def test_system_prompt_identity_uses_requested_wording():
    from friday.agent.prompts import get_default_system_prompt
    from friday.core.config import Settings

    prompt = get_default_system_prompt(Settings())
    assert (
        "You are FRIDAY, a Fully Responsive Intelligent Digital Assistant. "
        "You operate using a multi-provider architecture for text, voice, and vision."
    ) in prompt


def test_system_prompt_contains_greeting_rule():
    from friday.agent.prompts import get_default_system_prompt
    from friday.core.config import Settings

    prompt = get_default_system_prompt(Settings())
    assert "greeting" in prompt.lower()
    assert "Do not treat greetings as commands or tool targets" in prompt
    for greeting in ("'hi'", "'hello'", "'hey'"):
        assert greeting in prompt
