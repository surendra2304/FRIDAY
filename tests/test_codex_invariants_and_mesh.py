import os
from unittest.mock import patch
from pathlib import Path
import pytest

from friday.core.database import get_ephemeral_db_path
from friday.core.config import Settings
from friday.agent.router import SpecialistRouter, SPECIALIST_CONFIGS
from friday.ecosystem.fleet_client import FleetClient, CANONICAL_INTERNAL_MESH_URLS
from friday.autonomous.daily_rhythm import get_postgres_dsn as daily_rhythm_get_dsn
from friday.agent.execution_trace import get_postgres_dsn as trace_get_dsn


def test_get_ephemeral_db_path_linux_tmpfs():
    """Verify that on Linux with /dev/shm, ephemeral databases are placed in RAM tmpfs."""
    with patch("os.name", "posix"), \
         patch("os.path.isdir", return_value=True), \
         patch("os.access", return_value=True):
        path = get_ephemeral_db_path("test.db")
        assert path == "/dev/shm/test.db"


def test_get_ephemeral_db_path_fallback_windows():
    """Verify that on Windows/local dev, ephemeral databases default to ~/.friday/."""
    with patch("os.name", "nt"):
        path = get_ephemeral_db_path("test.db")
        assert path.endswith("test.db")
        assert ".friday" in path


def test_settings_sqlite_db_path_tmpfs():
    """Verify Settings.sqlite_db_path resolves via get_ephemeral_db_path for default paths."""
    settings = Settings()
    with patch("friday.core.database.get_ephemeral_db_path", return_value="/dev/shm/friday.db"):
        assert settings.sqlite_db_path == "/dev/shm/friday.db"


def test_specialist_router_canonical_mesh_in_production():
    """Verify router defaults to internal VPC mesh URLs (10.0.0.12x) in production."""
    router = SpecialistRouter()
    
    with patch.dict(os.environ, {"FRIDAY_ENV": "production"}, clear=False):
        # Clear peer env vars to test fallback to canonical_mesh_url
        with patch.dict(os.environ, {
            "INFERENCE_URL": "",
            "FRIDAY_INFERENCE_URL": "",
            "VYRALX_URL": "",
            "FRIDAY_VYRALX_URL": "",
            "SENTINEL_URL": "",
            "FRIDAY_SENTINEL_URL": "",
            "CORTEX_URL": "",
            "FRIDAY_CORTEX_URL": "",
            "FORGE_URL": "",
            "FRIDAY_FORGE_URL": "",
        }):
            assert router.get_agent_url("inference") == "http://10.0.0.121:8001"
            assert router.get_agent_url("vyralx") == "http://10.0.0.120:8010"
            assert router.get_agent_url("sentinel") == "http://10.0.0.120:8008"
            assert router.get_agent_url("cortex") == "http://10.0.0.120:8009"
            assert router.get_agent_url("forge") == "http://10.0.0.121:8006"


def test_fleet_client_canonical_mesh_in_production():
    """Verify FleetClient defaults to internal VPC mesh URLs in production."""
    with patch.dict(os.environ, {"FRIDAY_ENV": "production"}, clear=False):
        with patch.dict(os.environ, {
            "FRIDAY_INFERENCE_URL": "",
            "INFERENCE_URL": "",
            "FRIDAY_STRATEX_URL": "",
            "STRATEX_URL": "",
            "FRIDAY_VYRALX_URL": "",
            "VYRALX_URL": "",
        }):
            client = FleetClient()
            assert client.inference_url == "http://10.0.0.121:8001"
            assert client.stratex_url == "http://10.0.0.121:8003"
            assert client.vyralx_url == "http://10.0.0.120:8010"


def test_oracle_23ai_dsn_normalization():
    """Verify Oracle 23ai sync URLs are automatically normalized to asyncpg / oracledb_async."""
    oracle_sync = "oracle+oracledb://ADMIN:FridayUniverse2026%21%23Core@adb.ap-hyderabad-1.oraclecloud.com:1521/g7e6177242670c3_fridaycore_medium.adb.oraclecloud.com"
    expected_async = "oracle+oracledb_async://ADMIN:FridayUniverse2026%21%23Core@adb.ap-hyderabad-1.oraclecloud.com:1521/g7e6177242670c3_fridaycore_medium.adb.oraclecloud.com"
    
    with patch.dict(os.environ, {"DATABASE_URL": oracle_sync}):
        assert daily_rhythm_get_dsn() == expected_async
        assert trace_get_dsn() == expected_async

    oracle_plain = "oracle://ADMIN:FridayUniverse2026%21%23Core@adb.ap-hyderabad-1.oraclecloud.com:1521/g7e6177242670c3_fridaycore_medium.adb.oraclecloud.com"
    with patch.dict(os.environ, {"DATABASE_URL": oracle_plain}):
        assert daily_rhythm_get_dsn() == expected_async
        assert trace_get_dsn() == expected_async
