"""Mock tests for the Cerebras LLM provider, factory routing, and credential pool."""

from types import SimpleNamespace

import pytest

from friday.auth.credential_pool import (
    GeminiCredentialPool,
    OpenAICompatibleCredentialPool,
    cerebras_credential_pool,
    credential_pool,
)
from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role
from friday.llm.cerebras_provider import (
    CEREBRAS_DEFAULT_BASE_URL,
    CEREBRAS_DEFAULT_MODEL,
    CerebrasLLMProvider,
)
from friday.llm.factory import create_llm_provider


def _fake_response(content="OK"):
    msg = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _RateLimitLikeError(Exception):
    def __init__(self):
        super().__init__("Error code: 429 - Rate limit reached")
        self.status_code = 429


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def test_factory_creates_cerebras_provider():
    settings = Settings(llm_provider="cerebras", cerebras_api_key="TEST_CEREBRAS_KEY")
    provider = create_llm_provider(settings)
    assert isinstance(provider, CerebrasLLMProvider)
    assert provider.provider_name == "cerebras"
    assert provider.model == CEREBRAS_DEFAULT_MODEL == "gpt-oss-120b"
    assert provider.base_url == CEREBRAS_DEFAULT_BASE_URL


def test_factory_cerebras_model_override():
    settings = Settings(llm_provider="cerebras", cerebras_model="llama3.1-8b-4096")
    provider = create_llm_provider(settings)
    assert provider.model == "llama3.1-8b-4096"


def test_factory_cerebras_never_uses_gemini_pool(monkeypatch):
    def _explode(*a, **kw):
        raise AssertionError("Gemini credential pool must not be consulted for Cerebras")

    monkeypatch.setattr(GeminiCredentialPool, "get_active_key", _explode)
    settings = Settings(llm_provider="cerebras", cerebras_api_key="TEST_CEREBRAS_KEY")
    provider = create_llm_provider(settings)
    assert provider.api_key == "TEST_CEREBRAS_KEY"


# ---------------------------------------------------------------------------
# Generation behavior
# ---------------------------------------------------------------------------


def test_cerebras_generate_success():
    provider = CerebrasLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            return _fake_response(content="hello from cerebras")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.role == Role.ASSISTANT
    assert result.content == "hello from cerebras"
    assert calls == [CEREBRAS_DEFAULT_MODEL]


def test_cerebras_retries_transient_then_succeeds(monkeypatch):
    provider = CerebrasLLMProvider(api_key="k", max_retries=2)
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            attempts.append(1)
            if len(attempts) < 2:
                raise _RateLimitLikeError()
            return _fake_response(content="recovered")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "recovered"
    assert len(attempts) == 2


def test_cerebras_permanent_error_raises_without_retry(monkeypatch):
    provider = CerebrasLLMProvider(api_key="k", max_retries=2)
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            attempts.append(1)
            raise RuntimeError("Error code: 401 - invalid key")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError):
        provider.generate([Message(role=Role.USER, content="hi")])
    assert len(attempts) == 1  # 401 is not transient: no retries


def test_cerebras_masks_api_key_in_errors():
    provider = CerebrasLLMProvider(api_key="sk-super-secret")

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("auth failed for key sk-super-secret")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="hi")])
    assert "sk-super-secret" not in str(exc_info.value)


def test_cerebras_missing_sdk_raises_clean_error():
    provider = CerebrasLLMProvider(api_key="k")
    provider._client = None
    import friday.llm.cerebras_provider as cp
    original = cp._openai_sdk
    cp._openai_sdk = None
    try:
        with pytest.raises(LLMProviderError, match="openai"):
            provider.generate([Message(role=Role.USER, content="hi")])
    finally:
        cp._openai_sdk = original


# ---------------------------------------------------------------------------
# Credential pool
# ---------------------------------------------------------------------------


def test_cerebras_pool_distinct_from_all_other_pools():
    assert cerebras_credential_pool is not credential_pool
    assert cerebras_credential_pool.state_file.name == "cerebras_pool_state.json"


def test_cerebras_pool_loads_env_key(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "env-cerebras-key")
    pool = OpenAICompatibleCredentialPool(
        env_key_names=("FRIDAY_CEREBRAS_API_KEY", "CEREBRAS_API_KEY"),
        state_file_name="data/_test_cerebras_pool_state.json",
    )
    pool.reload()
    assert pool.get_active_key() == "env-cerebras-key"


def test_settings_load_cerebras_key(monkeypatch):
    monkeypatch.setenv("FRIDAY_CEREBRAS_API_KEY", "ck")
    s = Settings()
    assert s.cerebras_api_key == "ck"


# ---------------------------------------------------------------------------
# Mistral provider (deep fallback)
# ---------------------------------------------------------------------------


def test_factory_creates_mistral_provider():
    from friday.llm.factory import create_llm_provider
    from friday.llm.mistral_provider import MISTRAL_DEFAULT_MODEL, MistralLLMProvider

    settings = Settings(llm_provider="mistral", mistral_api_key="TEST_MISTRAL_KEY")
    provider = create_llm_provider(settings)
    assert isinstance(provider, MistralLLMProvider)
    assert provider.provider_name == "mistral"
    assert provider.model == MISTRAL_DEFAULT_MODEL == "mistral-large-latest"
    assert provider.base_url == "https://api.mistral.ai/v1"


def test_mistral_generate_success():
    from friday.llm.mistral_provider import MistralLLMProvider

    provider = MistralLLMProvider(api_key="k")

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            msg = SimpleNamespace(content="hello from mistral", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "hello from mistral"


def test_mistral_retries_transient_then_succeeds(monkeypatch):
    from friday.llm.mistral_provider import MistralLLMProvider

    provider = MistralLLMProvider(api_key="k", max_retries=2)
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = []

    class RateLimit429(Exception):
        def __init__(self):
            super().__init__("Error code: 429 - Rate limit reached")
            self.status_code = 429

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            attempts.append(1)
            if len(attempts) < 2:
                raise RateLimit429()
            msg = SimpleNamespace(content="recovered", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    assert provider.generate([Message(role=Role.USER, content="hi")]).content == "recovered"


def test_mistral_permanent_error_and_key_masking():
    from friday.llm.mistral_provider import MistralLLMProvider

    provider = MistralLLMProvider(api_key="sk-super-mistral")

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("auth failed for key sk-super-mistral")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="hi")])
    assert "sk-super-mistral" not in str(exc_info.value)


def test_mistral_pool_distinct_and_settings(monkeypatch):
    from friday.auth.credential_pool import OpenAICompatibleCredentialPool, mistral_credential_pool

    assert mistral_credential_pool.state_file.name == "mistral_pool_state.json"
    monkeypatch.setenv("MISTRAL_API_KEY", "env-mistral-key")
    pool = OpenAICompatibleCredentialPool(
        env_key_names=("FRIDAY_MISTRAL_API_KEY", "MISTRAL_API_KEY"),
        state_file_name="data/_test_mistral_pool_state.json",
    )
    pool.reload()
    assert pool.get_active_key() == "env-mistral-key"

    monkeypatch.setenv("FRIDAY_MISTRAL_API_KEY", "mk")
    assert Settings().mistral_api_key == "mk"


def test_mistral_never_uses_gemini_pool(monkeypatch):
    from friday.auth.credential_pool import GeminiCredentialPool
    from friday.llm.factory import create_llm_provider
    from friday.llm.mistral_provider import MistralLLMProvider

    def _explode(*a, **kw):
        raise AssertionError("Gemini pool must not be consulted for Mistral")

    monkeypatch.setattr(GeminiCredentialPool, "get_active_key", _explode)
    provider = create_llm_provider(Settings(llm_provider="mistral", mistral_api_key="mk"))
    assert provider.api_key == "mk"
