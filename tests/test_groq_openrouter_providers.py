"""Mock tests for Groq and OpenRouter LLM providers, factory routing, and credential pools."""

import json
from types import SimpleNamespace

import pytest

from friday.auth.credential_pool import (
    GeminiCredentialPool,
    OpenAICompatibleCredentialPool,
    credential_pool,
    groq_credential_pool,
    openrouter_credential_pool,
)
from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role
from friday.llm.factory import create_llm_provider
from friday.llm.groq_provider import (
    GROQ_DEFAULT_MODEL,
    GROQ_FALLBACK_MODEL,
    GroqLLMProvider,
)
from friday.llm.openrouter_provider import OpenRouterLLMProvider


def _fake_response(content="OK", tool_calls=None):
    tc_objs = None
    if tool_calls:
        tc_objs = [
            SimpleNamespace(id=f"call_{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
            for i, (n, a) in enumerate(tool_calls)
        ]
    msg = SimpleNamespace(content=content, tool_calls=tc_objs)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class _RateLimitLikeError(Exception):
    def __init__(self):
        super().__init__("Error code: 429 - Rate limit reached")
        self.status_code = 429


# ---------------------------------------------------------------------------
# Factory routing
# ---------------------------------------------------------------------------


def test_factory_creates_groq_provider():
    settings = Settings(llm_provider="groq", groq_api_key="TEST_GROQ_KEY")
    provider = create_llm_provider(settings)
    assert isinstance(provider, GroqLLMProvider)
    assert provider.provider_name == "groq"
    assert provider.model == GROQ_DEFAULT_MODEL == "llama-3.3-70b-versatile"
    assert provider.fallback_model == "llama-3.1-8b-instant"


def test_factory_creates_openrouter_provider():
    settings = Settings(llm_provider="openrouter", openrouter_api_key="TEST_OR_KEY")
    provider = create_llm_provider(settings)
    assert isinstance(provider, OpenRouterLLMProvider)
    assert provider.provider_name == "openrouter"


def test_factory_groq_model_override():
    settings = Settings(llm_provider="groq", groq_model="mixtral-8x7b-32768")
    provider = create_llm_provider(settings)
    assert provider.model == "mixtral-8x7b-32768"


def test_factory_does_not_use_gemini_pool_for_groq(monkeypatch):
    """Text providers must never pull credentials from the Gemini pool."""
    def _explode(*a, **kw):
        raise AssertionError("Gemini credential pool must not be consulted for Groq")

    monkeypatch.setattr(GeminiCredentialPool, "get_active_key", _explode)
    settings = Settings(llm_provider="groq", groq_api_key="TEST_GROQ_KEY")
    provider = create_llm_provider(settings)
    assert isinstance(provider, GroqLLMProvider)
    assert provider.api_key == "TEST_GROQ_KEY"


def test_groq_provider_uses_own_pool_when_no_explicit_key(monkeypatch):
    monkeypatch.setattr(groq_credential_pool.__class__, "get_active_key", lambda self: "POOL_GROQ_KEY")
    provider = GroqLLMProvider(credential_pool=groq_credential_pool)
    assert provider.api_key == "POOL_GROQ_KEY"


# ---------------------------------------------------------------------------
# Groq generation & 429 model fallback
# ---------------------------------------------------------------------------


def test_groq_generate_success():
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            return _fake_response(content="hello from groq")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.role == Role.ASSISTANT
    assert result.content == "hello from groq"
    assert calls == [GROQ_DEFAULT_MODEL]


def test_groq_rate_limit_falls_back_to_instant_model():
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise _RateLimitLikeError()
            return _fake_response(content="fallback ok")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "fallback ok"
    assert calls == [GROQ_DEFAULT_MODEL, GROQ_FALLBACK_MODEL]


def test_groq_rate_limit_on_both_models_raises():
    provider = GroqLLMProvider(api_key="k")

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            raise _RateLimitLikeError()

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError):
        provider.generate([Message(role=Role.USER, content="hi")])


def test_groq_non_rate_limit_error_does_not_fallback():
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            raise RuntimeError("Error code: 401 - invalid key")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError):
        provider.generate([Message(role=Role.USER, content="hi")])
    assert calls == [GROQ_DEFAULT_MODEL]  # no fallback attempt on 401


def test_groq_tool_call_parsing():
    provider = GroqLLMProvider(api_key="k")

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            return _fake_response(
                content="",
                tool_calls=[("get_system_info", {"detailed": True})],
            )

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate(
        [Message(role=Role.USER, content="system info")],
        tools=[{"type": "function", "function": {"name": "get_system_info", "parameters": {}}}],
    )
    assert result.tool_calls is not None
    assert result.tool_calls[0].name == "get_system_info"
    assert result.tool_calls[0].arguments == {"detailed": True}


# ---------------------------------------------------------------------------
# OpenRouter generation
# ---------------------------------------------------------------------------


def test_openrouter_generate_success():
    provider = OpenRouterLLMProvider(api_key="k", max_retries=0)

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            assert kwargs["model"] == provider.model
            return _fake_response(content="hello from openrouter")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "hello from openrouter"


def test_openrouter_retries_transient_then_succeeds(monkeypatch):
    provider = OpenRouterLLMProvider(api_key="k", max_retries=2)
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


def test_openrouter_permanent_error_raises(monkeypatch):
    provider = OpenRouterLLMProvider(api_key="k", max_retries=2)

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            raise RuntimeError("Error code: 401 - invalid key")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError):
        provider.generate([Message(role=Role.USER, content="hi")])


# ---------------------------------------------------------------------------
# Credential pools
# ---------------------------------------------------------------------------


def test_non_gemini_pools_are_distinct_from_gemini_pool():
    assert groq_credential_pool is not credential_pool
    assert openrouter_credential_pool is not credential_pool
    assert groq_credential_pool is not openrouter_credential_pool


def test_groq_pool_loads_env_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "env-groq-key")
    pool = OpenAICompatibleCredentialPool(
        env_key_names=("FRIDAY_GROQ_API_KEY", "GROQ_API_KEY"),
        state_file_name="data/_test_groq_pool_state.json",
    )
    pool.reload()
    assert pool.get_active_key() == "env-groq-key"


def test_openrouter_pool_loads_prefixed_env_key(monkeypatch):
    monkeypatch.setenv("FRIDAY_OPENROUTER_API_KEY", "env-or-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    pool = OpenAICompatibleCredentialPool(
        env_key_names=("FRIDAY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        state_file_name="data/_test_or_pool_state.json",
    )
    pool.reload()
    assert pool.get_active_key() == "env-or-key"


def test_settings_load_groq_and_openrouter_keys(monkeypatch):
    monkeypatch.setenv("FRIDAY_GROQ_API_KEY", "gk")
    monkeypatch.setenv("OPENROUTER_API_KEY", "ork")
    s = Settings()
    assert s.groq_api_key == "gk"
    assert s.openrouter_api_key == "ork"


def test_missing_sdk_raises_clean_error():
    provider = GroqLLMProvider(api_key="k")
    provider._client = None
    import friday.llm.groq_provider as gp
    original = gp._openai_sdk
    gp._openai_sdk = None
    try:
        with pytest.raises(LLMProviderError, match="openai"):
            provider.generate([Message(role=Role.USER, content="hi")])
    finally:
        gp._openai_sdk = original


# ---------------------------------------------------------------------------
# 404 model_not_found fallback (universal model llama3-8b-8192)
# ---------------------------------------------------------------------------


class _ModelNotFound404Error(Exception):
    def __init__(self, model="llama-3.3-70b-versatile"):
        super().__init__(f"Error code: 404 - model_not_found: model '{model}' has been decommissioned")
        self.status_code = 404


def test_groq_404_on_primary_retries_with_universal_model():
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise _ModelNotFound404Error()
            return _fake_response(content="universal rescue")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "universal rescue"
    assert calls == ["llama-3.3-70b-versatile", "llama3-8b-8192"]


def test_groq_404_on_primary_and_universal_raises_for_chain_failover():
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            raise _ModelNotFound404Error(kwargs["model"])

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="hi")])
    assert "model_not_found" in str(exc_info.value) or "404" in str(exc_info.value)
    assert calls == ["llama-3.3-70b-versatile", "llama3-8b-8192"]


def test_groq_429_then_fallback_404_uses_universal_model():
    """429 on primary -> fast fallback 404 -> universal succeeds."""
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise _RateLimitLikeError()
            if len(calls) == 2:
                raise _ModelNotFound404Error()
            return _fake_response(content="cascade rescue")

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    result = provider.generate([Message(role=Role.USER, content="hi")])
    assert result.content == "cascade rescue"
    assert calls == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192"]


def test_groq_429_on_universal_after_404_raises():
    """404 on primary -> universal 429 -> LLMProviderError (chain advances to Cerebras)."""
    provider = GroqLLMProvider(api_key="k")
    calls = []

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise _ModelNotFound404Error()
            raise _RateLimitLikeError()

    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions))
    with pytest.raises(LLMProviderError):
        provider.generate([Message(role=Role.USER, content="hi")])
    assert calls == ["llama-3.3-70b-versatile", "llama3-8b-8192"]


def test_groq_universal_fallback_model_configurable():
    provider = GroqLLMProvider(api_key="k", universal_fallback_model="llama3-70b-8192")
    assert provider.universal_fallback_model == "llama3-70b-8192"
