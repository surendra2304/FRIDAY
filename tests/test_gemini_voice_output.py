"""Regression tests for Gemini TTS output parsing and failure behavior."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from friday.core.exceptions import VoiceError
from friday.voice.gemini_provider import GeminiVoiceOutput


def response_with_audio(data=b"\x01\x00\x02\x00", mime_type="audio/pcm;rate=24000"):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type=mime_type))
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate])


def test_empty_input_does_not_create_client_or_make_request():
    output = GeminiVoiceOutput(api_key="test-key", client=None)
    assert output.synthesize("  \n ") == b""
    assert output._client is None


def test_synthesize_returns_audio_from_genai_response():
    client = MagicMock()
    client.models.generate_content.return_value = response_with_audio()
    output = GeminiVoiceOutput(api_key="test-key", client=client, voice_name="Kore")

    audio = output.synthesize("Hello, FRIDAY.")

    assert audio == b"\x01\x00\x02\x00"
    client.models.generate_content.assert_called_once()
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash-preview-tts"
    assert kwargs["contents"] == "Hello, FRIDAY."
    assert kwargs["config"].response_modalities == ["AUDIO"]


def test_synthesize_accepts_bytearray_payload():
    client = MagicMock()
    client.models.generate_content.return_value = response_with_audio(bytearray(b"audio"))
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    assert output.synthesize("Speak") == b"audio"


def test_synthesize_rejects_non_audio_inline_payload():
    client = MagicMock()
    client.models.generate_content.return_value = response_with_audio(b"not audio", "image/png")
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    with pytest.raises(VoiceError, match="no audio payload"):
        output.synthesize("Speak")


def test_synthesize_rejects_empty_provider_response():
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(candidates=[])
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    with pytest.raises(VoiceError, match="no audio payload"):
        output.synthesize("Speak")


def test_synthesize_wraps_provider_errors_without_exposing_details():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("provider exploded with secret-token-abc")
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    with pytest.raises(VoiceError, match="Check provider configuration") as exc:
        output.synthesize("Speak")

    assert "secret-token-abc" not in str(exc.value)


def test_synthesize_requires_credentials_only_for_nonempty_text():
    output = GeminiVoiceOutput(api_key=None, client=None)
    with pytest.raises(VoiceError, match="API key is required"):
        output.synthesize("Speak")
