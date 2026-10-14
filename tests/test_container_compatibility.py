"""Test suite verifying FRIDAY container standards, mesh architecture, and health routes."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_mesh_urls_and_ports() -> None:
    """Verify all specialist peer agents in friday_mesh use port 8000 and zero onrender URLs."""
    from friday.core.config import get_settings

    settings = get_settings(reload=True)
    peers = [
        ("cortex", settings.cortex_url),
        ("forge", settings.forge_url),
        ("futuris", settings.futuris_url),
        ("inference", settings.inference_url),
        ("intelx", settings.intelx_url),
        ("memora", settings.memora_url),
        ("sentinel", settings.sentinel_url),
        ("stratex", settings.stratex_url),
    ]
    for name, url in peers:
        assert "onrender.com" not in url, f"Peer {name} has deprecated onrender.com URL: {url}"
        assert ":8000" in url, f"Peer {name} must run on internal mesh port 8000: {url}"


def test_dockerfile_and_dockerignore() -> None:
    """Verify Dockerfile and .dockerignore exist and contain hardened enterprise container setup."""
    dockerfile_path = REPO_ROOT / "Dockerfile"
    dockerignore_path = REPO_ROOT / ".dockerignore"

    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"
    assert dockerignore_path.exists(), ".dockerignore must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in content
    assert "EXPOSE 10000" in content
    assert "appuser" in content, "Dockerfile must configure non-root user appuser"
    assert "HEALTHCHECK" in content, "Dockerfile must configure container HEALTHCHECK"

    ignore_content = dockerignore_path.read_text(encoding="utf-8")
    assert ".env" in ignore_content, ".env must be ignored in .dockerignore"
    assert ".git" in ignore_content, ".git must be ignored in .dockerignore"


def test_server_app_health_routes() -> None:
    """Verify FastAPI application exposes /health and /api/health with required fields."""
    from fastapi.testclient import TestClient
    from friday.api.server import app

    routes = [route.path for route in app.routes]
    assert "/health" in routes, "Server must expose /health endpoint for container health checks"
    assert "/api/health" in routes, "Server must expose /api/health endpoint"
    assert "/messages" in routes, "Server must expose FastMCP /messages endpoint"

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("overall") == "healthy"
    assert data.get("service") == "friday_core"
    assert data.get("evidence_class") == "process_liveness"
    assert "observed_at" in data
    assert data.get("peers_mesh") == "connected"


def test_windows_friday_non_windows_safety() -> None:
    """Verify WindowsFridayController does not crash when initialized on non-Windows hosts."""
    import ctypes
    from friday.devices.windows_friday import WindowsFridayController

    # Temporarily hide windll if present
    with patch.object(ctypes, "windll", None, create=True):
        ctrl = WindowsFridayController()
        # Should initialize gracefully without raising AttributeError
        assert ctrl is not None
        # _send_key_event should no-op safely
        ctrl._send_key_event(0x20)
