"""Regression tests for Gemini TTS output parsing and failure behavior."""
import io
import wave
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
    assert kwargs["model"] == "gemini-3.8-flash-tts"
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


def test_synthesize_requires_credentials_only_for_nonempty_text(monkeypatch):
    from types import SimpleNamespace
    import friday.voice.gemini_provider as provider_module

    monkeypatch.setattr(
        provider_module,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key=None, llm_api_key=None, voice_tts_model="gemini-3.8-flash-tts", voice_name="Kore"),
    )
    output = GeminiVoiceOutput(api_key=None, client=None)
    with pytest.raises(VoiceError, match="API key is required"):
        output.synthesize("Speak")

def make_wav(frames=b"\\x01\\x00\\x02\\x00", sample_rate=24000, channels=1, sample_width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return buffer.getvalue()


def test_synthesize_unwraps_wav_container_to_raw_pcm():
    client = MagicMock()
    wav_data = make_wav()
    client.models.generate_content.return_value = response_with_audio(wav_data, "audio/wav")
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    assert output.synthesize("Speak") == b"\\x01\\x00\\x02\\x00"


def test_synthesize_rejects_wav_sample_rate_mismatch():
    client = MagicMock()
    client.models.generate_content.return_value = response_with_audio(make_wav(sample_rate=16000), "audio/wav")
    output = GeminiVoiceOutput(api_key="test-key", client=client, sample_rate=24000)

    with pytest.raises(VoiceError, match="does not match"):
        output.synthesize("Speak")


def test_synthesize_rejects_stereo_wav():
    client = MagicMock()
    client.models.generate_content.return_value = response_with_audio(make_wav(channels=2), "audio/wav")
    output = GeminiVoiceOutput(api_key="test-key", client=client)

    with pytest.raises(VoiceError, match="mono 16-bit PCM"):
        output.synthesize("Speak")
