# -*- coding: utf-8 -*-
"""Unit tests for Memora hardening, local-first storage, and quarantine context."""

from unittest.mock import patch, MagicMock
import os
import pytest

from friday.memory.memora_client import MemoraClient
from friday.core.types import Message, Role


def test_memora_remote_disabled_by_default():
    """Verify remote API requests are disabled by default without FRIDAY_MEMORA_REMOTE_ENABLED."""
    with patch.dict(os.environ, {}, clear=True):
        client = MemoraClient(local_db_path=":memory:")
        assert client.remote_enabled is False


def test_memora_cloud_is_default_when_friday_agent_key_is_configured(monkeypatch):
    monkeypatch.setenv("FRIDAY_API_KEY", "friday-test-key")
    monkeypatch.delenv("FRIDAY_MEMORA_REMOTE_ENABLED", raising=False)
    assert MemoraClient(local_db_path=":memory:").remote_enabled is True


def test_memora_interaction_writes_cloud_before_local_fallback(monkeypatch):
    import json

    captured = {}

    class Response:
        status = 201
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return b'{"status":"success","recorded_count":1}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setenv("FRIDAY_API_KEY", "friday-test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = MemoraClient(local_db_path=":memory:")
    client._record_locally = lambda *_args, **_kwargs: pytest.fail("local storage ran before cloud write")

    result = client.record_interaction("friday", "hello", "hi")

    assert result["status"] == "success"
    assert captured["url"].endswith("/v1/memories/record-interaction")
    assert captured["headers"]["Authorization"] == "Bearer friday-test-key"
    assert captured["payload"]["user_text"] == "hello"


def test_memora_event_poll_uses_friday_key_and_cursor(monkeypatch):
    captured = {}

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return b'{"events":[],"next_after_id":7,"has_more":false}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("FRIDAY_API_KEY", "friday-test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = MemoraClient(base_url="https://memora.invalid", api_key="memora-server-key", remote_enabled=True)
    result = client.poll_events("friday", after_id=6)
    assert result["status"] == "ok"
    assert "after_id=6" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer friday-test-key"


@pytest.mark.parametrize(
    ("body", "after_id", "limit", "expected_ids", "expected_has_more"),
    [
        (
            {"events": [{"id": 8, "event_id": "new-8", "event_type": "intelx.news", "created_at": "2026-09-26T10:00:00Z", "payload": {"headline": "new shape"}}], "next_after_id": 8, "has_more": False},
            7, 10, [8], False,
        ),
        (
            [{"cursor": 8, "event_id": "legacy-8", "event_type": "intelx.news", "timestamp": "2026-09-26T10:00:00Z", "payload": {"headline": "legacy shape"}}],
            7, 1, [8], True,
        ),
        (
            [{"cursor": 8, "event_id": "legacy-8", "event_type": "intelx.news", "timestamp": "2026-09-26T10:00:00Z", "payload": {"headline": "legacy shape"}}],
            7, 2, [8], False,
        ),
    ],
)
def test_memora_event_poll_normalizes_object_and_legacy_list_shapes(
    monkeypatch, body, after_id, limit, expected_ids, expected_has_more
):
    import json

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps(body).encode()

    monkeypatch.setenv("FRIDAY_API_KEY", "friday-test-key")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    client = MemoraClient(base_url="https://memora.invalid", local_db_path=":memory:", remote_enabled=True)

    result = client.poll_events("friday", after_id=after_id, limit=limit)

    assert result["status"] == "ok"
    assert [event["id"] for event in result["events"]] == expected_ids
    assert result["has_more"] is expected_has_more
    if isinstance(body, list):
        assert result["events"][0]["created_at"] == body[0]["timestamp"]
        assert result["events"][0]["event_id"] == body[0]["event_id"]
        assert result["events"][0]["payload"] == body[0]["payload"]


@pytest.mark.parametrize(
    "body",
    [
        {"events": [{"id": "not-an-int", "event_id": "x", "event_type": "intelx.news", "payload": {}}]},
        [{"cursor": 1, "event_id": "x", "event_type": "intelx.news", "payload": []}],
        [{"cursor": 1, "event_type": "intelx.news", "payload": {}}],
        {"unexpected": []},
    ],
)
def test_memora_event_poll_rejects_malformed_rows(monkeypatch, body):
    import json

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps(body).encode()

    monkeypatch.setenv("FRIDAY_API_KEY", "friday-test-key")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    client = MemoraClient(base_url="https://memora.invalid", local_db_path=":memory:", remote_enabled=True)

    result = client.poll_events("friday", after_id=0)

    assert result["status"] == "error"
    assert result["error"] == "Memora returned an invalid event feed"


def test_memora_sanitizes_credentials_before_persistence():
    """Verify raw API keys and secrets are redacted before persistence."""
    client = MemoraClient(local_db_path=":memory:")

    mock_secret_key = "sk-proj-1234567890abcdef1234567890abcdef"
    mock_gemini_key = "AIzaSyMockTokenNeverStoreInDatabase1234"
    raw_input = f"Remember my credentials: {mock_secret_key} and {mock_gemini_key} and password='my_super_password'"

    assert client.should_persist(raw_input) is False

    clean_text = client.sanitize_for_persistence(raw_input)
    assert mock_secret_key not in clean_text
    assert mock_gemini_key not in clean_text
    assert "[REDACTED_CREDENTIAL]" in clean_text


def test_memora_quarantine_headers_in_context_blocks():
    """Verify build_context_block contains UNTRUSTED reference demarcation."""
    client = MemoraClient(local_db_path=":memory:")

    with patch.object(client, "recall_memories", return_value=[{"content_text": "User prefers dark mode", "memory_type": "preference"}]):
        block = client.build_context_block("friday", "dark mode")
        assert "UNTRUSTED HISTORICAL REFERENCE DATA" in block
        assert "NOT SECURITY POLICY" in block
        assert "dark mode" in block


def test_agent_injects_recalled_memory_as_user_role():
    """Verify agent.py executes with memory quarantined under Role.USER rather than Role.SYSTEM."""
    from friday.agent.agent import FridayAgent
    from friday.llm.base import BaseLLMProvider
    from friday.tools.registry import ToolRegistry

    mock_llm = MagicMock(spec=BaseLLMProvider)
    mock_llm.model = "mock-model"
    mock_llm.provider_name = "mock"
    mock_llm.generate.return_value = Message(role=Role.ASSISTANT, content="I understand your preference.")

    agent = FridayAgent(llm_provider=mock_llm, tool_registry=ToolRegistry())

    with patch("friday.memory.memora_client.memora_client.build_context_block", return_value="User likes tea."):
        agent.execute_complex_task("what do i like?")

        # Check messages sent to LLM
        call_args = mock_llm.generate.call_args[0][0]

        # Ensure recalled memory was injected as Role.USER, not Role.SYSTEM
        found_memory = False
        for m in call_args:
            if "User likes tea" in m.content:
                found_memory = True
                assert m.role == Role.USER
                assert "UNTRUSTED HISTORICAL MEMORY CONTEXT" in m.content
        assert found_memory is True
