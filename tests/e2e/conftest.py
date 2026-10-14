"""Pytest fixtures for FRIDAY Core Gateway E2E Test Suite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator, Generator
from unittest.mock import patch
import pytest
import httpx
from fastapi.testclient import TestClient

from friday.api.server import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient fixture configured to capture all unhandled exceptions."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """AsyncClient fixture bound to the ASGI application for async request workflows."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def temp_sqlite_db(tmp_path: Path) -> Path:
    """Fixture providing a fresh isolated temporary SQLite database file path."""
    db_file = tmp_path / "e2e_test.db"
    return db_file


@pytest.fixture
def clean_env() -> Generator[dict[str, str], None, None]:
    """Fixture providing a controlled environment dictionary for tests modifying os.environ."""
    original = dict(os.environ)
    yield original
    os.environ.clear()
    os.environ.update(original)
