from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from friday.api import server


@pytest.mark.asyncio
async def test_remote_control_requires_non_example_key(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(server, "settings", SimpleNamespace(api_key="friday_universe_api"))
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    with pytest.raises(HTTPException) as exc:
        await server._require_control_access(request)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_remote_control_checks_bearer_key_constant_time(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setattr(server, "settings", SimpleNamespace(api_key="a-long-configured-secret"))
    request = SimpleNamespace(headers={"authorization": "Bearer a-long-configured-secret"}, client=SimpleNamespace(host="127.0.0.1"))
    assert await server._require_control_access(request) is None

    request.headers = {"x-friday-api-key": "incorrect"}
    with pytest.raises(HTTPException) as exc:
        await server._require_control_access(request)
    assert exc.value.status_code == 401
