"""Tests for LLM provider abstractions."""

import pytest
from friday.core.config import Settings
from friday.core.exceptions import ConfigError, LLMProviderError
from friday.core.types import Message, Role, ToolCall
from friday.llm.factory import create_llm_provider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider


def test_mock_provider_generation():
    provider = MockLLMProvider(model="test-mock")
    messages = [Message(role=Role.USER, content="Hello FRIDAY")]
    response = provider.generate(messages)

    assert response.role == Role.ASSISTANT
    assert "Hello FRIDAY" in response.content
    assert provider.provider_name == "mock"


def test_mock_provider_tool_trigger():
    provider = MockLLMProvider()
    messages = [Message(role=Role.USER, content="Please check system info")]
    tools = [
        {
            "type": "function",
            "function": {"name": "get_system_info", "description": "Get system info", "parameters": {}},
        }
    ]
    response = provider.generate(messages, tools=tools)
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_system_info"


def test_factory_creation():
    mock_settings = Settings(llm_provider="mock")
    provider = create_llm_provider(mock_settings)
    assert isinstance(provider, MockLLMProvider)

    openai_settings = Settings(llm_provider="openai", llm_api_key="TEST_OPENAI_API_KEY")
    openai_provider = create_llm_provider(openai_settings)
    assert isinstance(openai_provider, OpenAILLMProvider)


def test_factory_invalid_provider():
    bad_settings = Settings(llm_provider="unsupported_ai")
    with pytest.raises(ConfigError):
        create_llm_provider(bad_settings)


def test_openai_provider_error_handling_json():
    from unittest import mock
    provider = OpenAILLMProvider(api_key="TEST_OPENAI_API_KEY", base_url="https://api.mock.com")

    # Mock status code 400 — simulate the API echoing back the api_key in the error body.
    # OpenAI provider masks self.api_key wherever it appears in error details.
    api_key = provider.api_key  # "TEST_OPENAI_API_KEY"
    mock_resp = mock.Mock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": {"message": f"Invalid API key {api_key} provided."}}

    with mock.patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Hello")])

        # Verify JSON parsed error message is raised
        assert "Invalid API key" in str(exc_info.value)
        # Verify the API key is masked in the exception message
        assert api_key not in str(exc_info.value)
        assert "***" in str(exc_info.value)


def test_openai_provider_error_handling_html_truncation():
    from unittest import mock
    provider = OpenAILLMProvider(api_key="TEST_OPENAI_API_KEY", base_url="https://api.mock.com")

    # Mock status 502 with massive HTML error page
    mock_resp = mock.Mock()
    mock_resp.status_code = 502
    mock_resp.text = "<html>" + ("<body>Internal Server Error page content body spam 502 Bad Gateway</body>" * 20) + "</html>"
    mock_resp.json.side_effect = Exception("Not JSON")

    with mock.patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Hello")])

        # Verify truncated output
        err_msg = str(exc_info.value)
        assert len(err_msg) < 500
        assert "... [TRUNCATED]" in err_msg


def test_factory_gemini_creation():
    gemini_settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY")
    gemini_provider = create_llm_provider(gemini_settings)
    assert isinstance(gemini_provider, GeminiLLMProvider)
    assert gemini_provider.provider_name == "gemini"
    assert gemini_provider.api_key == "TEST_GEMINI_API_KEY"


def test_gemini_missing_api_key():
    provider = GeminiLLMProvider(api_key="")
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Hello")])
    assert "Gemini API key is required" in str(exc_info.value)


def test_gemini_request_translation():
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-2.5-flash")
    messages = [
        Message(role=Role.SYSTEM, content="You are FRIDAY."),
        Message(role=Role.USER, content="What is the weather?"),
        Message(
            role=Role.ASSISTANT,
            content="Checking weather...",
            tool_calls=[ToolCall(id="call_1", name="get_weather", arguments={"city": "London"})],
        ),
        Message(
            role=Role.TOOL,
            name="get_weather",
            content='{"temp": "18C", "condition": "Cloudy"}',
            tool_call_id="call_1",
        ),
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]

    payload = provider._build_gemini_payload(messages, tools)

    # Check system instruction
    assert "systemInstruction" in payload
    assert payload["systemInstruction"]["parts"][0]["text"] == "You are FRIDAY."

    # Check contents length & structure
    contents = payload["contents"]
    assert len(contents) == 3  # user, model, function

    # User message
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0]["text"] == "What is the weather?"

    # Model message with text and functionCall
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["text"] == "Checking weather..."
    assert contents[1]["parts"][1]["functionCall"]["name"] == "get_weather"
    assert contents[1]["parts"][1]["functionCall"]["args"] == {"city": "London"}

    # Function response message
    assert contents[2]["role"] == "function"
    func_resp = contents[2]["parts"][0]["functionResponse"]
    assert func_resp["name"] == "get_weather"
    assert func_resp["response"] == {"temp": "18C", "condition": "Cloudy"}

    # Check tools declaration
    assert "tools" in payload
    assert len(payload["tools"][0]["functionDeclarations"]) == 1
    decl = payload["tools"][0]["functionDeclarations"][0]
    assert decl["name"] == "get_weather"
    assert decl["parameters"]["required"] == ["city"]


def test_gemini_direct_response_generation():
    from unittest import mock
    from google.genai import types

    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY", model="gemini-2.5-flash")
    mock_resp = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Hello! I am FRIDAY, your assistant.")],
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = mock_resp

    response = provider.generate([Message(role=Role.USER, content="Hello")])
    assert response.role == Role.ASSISTANT
    assert response.content == "Hello! I am FRIDAY, your assistant."
    assert response.tool_calls is None


def test_gemini_tool_call_response_generation():
    from unittest import mock
    from google.genai import types

    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY", model="gemini-2.5-flash")
    mock_resp = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(text="Let me calculate that for you."),
                        types.Part.from_function_call(
                            name="calculator",
                            args={"expression": "25 * 4"},
                        ),
                    ],
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = mock_resp

    response = provider.generate([Message(role=Role.USER, content="What is 25 * 4?")])
    assert response.role == Role.ASSISTANT
    assert response.content == "Let me calculate that for you."
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "calculator"
    assert response.tool_calls[0].arguments == {"expression": "25 * 4"}


def test_gemini_error_handling_and_secret_masking():
    from unittest import mock
    secret_key = "TEST_GEMINI_API_KEY"
    provider = GeminiLLMProvider(api_key=secret_key)

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = Exception(
        f"API key {secret_key} is not valid. Please pass a valid API key."
    )

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Hi")])

    err_msg = str(exc_info.value)
    assert "API key" in err_msg
    assert secret_key not in err_msg
    assert "***" in err_msg


def test_gemini_safety_block_handling():
    from unittest import mock
    from google.genai import types

    provider = GeminiLLMProvider(api_key="test-key")
    mock_resp = types.GenerateContentResponse(
        candidates=[],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason.SAFETY,
        ),
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = mock_resp

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Dangerous input")])

    assert "blocked by safety filters" in str(exc_info.value)


