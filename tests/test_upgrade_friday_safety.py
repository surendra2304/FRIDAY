"""Safety regression tests for the legacy FRIDAY upgrade script."""

import importlib.util
import logging
from pathlib import Path

import pytest


def _load_upgrade_script():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "upgrade_friday.py"
    spec = importlib.util.spec_from_file_location("friday_upgrade_legacy", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_upgrade_entrypoint_is_non_mutating(monkeypatch, tmp_path, caplog):
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.INFO, logger="friday_upgrade")
    script = _load_upgrade_script()

    script.main()

    assert "No source files" in caplog.text
    assert list(tmp_path.iterdir()) == []


def test_legacy_upgrade_cannot_push_to_main():
    script = _load_upgrade_script()
    with pytest.raises(RuntimeError, match="Automatic Git staging/commit/push is disabled"):
        script.commit_and_push()
