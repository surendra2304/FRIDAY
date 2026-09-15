"""Test suite verifying FRIDAY cloud container and Render deployment compatibility."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_render_yaml_validity() -> None:
    """Verify render.yaml exists and adheres to Render Blueprint specification."""
    render_yaml_path = REPO_ROOT / "render.yaml"
    assert render_yaml_path.exists(), "render.yaml must exist at repository root"

    with open(render_yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert "services" in config, "render.yaml must define a 'services' list"
    assert len(config["services"]) >= 1, "render.yaml must have at least one service defined"

    web_svc = config["services"][0]
    assert web_svc.get("type") == "web", "Service type must be 'web'"
    assert web_svc.get("runtime") == "docker", "Runtime should default to 'docker'"
    assert web_svc.get("healthCheckPath") == "/health", "healthCheckPath must be '/health'"

    env_vars = {item["key"]: item.get("value") for item in web_svc.get("envVars", [])}
    assert "PORT" in env_vars, "PORT must be configured in render.yaml envVars"
    assert "HOST" in env_vars, "HOST must be configured in render.yaml envVars"


def test_dockerfile_and_dockerignore() -> None:
    """Verify Dockerfile and .dockerignore exist and contain correct cloud setup."""
    dockerfile_path = REPO_ROOT / "Dockerfile"
    dockerignore_path = REPO_ROOT / ".dockerignore"

    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"
    assert dockerignore_path.exists(), ".dockerignore must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in content
    assert "uvicorn friday.api.server:app" in content
    assert "EXPOSE 10000" in content

    ignore_content = dockerignore_path.read_text(encoding="utf-8")
    assert ".env" in ignore_content, ".env must be ignored in .dockerignore"
    assert ".git" in ignore_content, ".git must be ignored in .dockerignore"


def test_server_app_health_routes() -> None:
    """Verify FastAPI application has both /health and /api/health routes."""
    from friday.api.server import app

    routes = [route.path for route in app.routes]
    assert "/health" in routes, "Server must expose /health endpoint for Render health checks"
    assert "/api/health" in routes, "Server must expose /api/health endpoint"
    assert "/messages" in routes, "Server must expose FastMCP /messages endpoint"


def test_windows_friday_non_windows_safety() -> None:
    """Verify WindowsFridayController does not crash when initialized on non-Windows hosts."""
    import ctypes
    from friday.devices.windows_friday import WindowsFridayController

    # Temporarily hide windll if present
    with patch.object(ctypes, "windll", None, create=False):
        ctrl = WindowsFridayController()
        # Should initialize gracefully without raising AttributeError
        assert ctrl is not None
        # _send_key_event should no-op safely
        ctrl._send_key_event(0x20)
