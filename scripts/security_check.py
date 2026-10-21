"""Compatibility entrypoint for FRIDAY's repository-level security scanner."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security_check import (  # noqa: E402
    SECRET_PATTERNS,
    git_ls_env,
    is_safe_test_fixture,
    main,
    run_security_check,
    scan_for_real_secrets,
)

__all__ = [
    "SECRET_PATTERNS",
    "git_ls_env",
    "is_safe_test_fixture",
    "run_security_check",
    "scan_for_real_secrets",
    "main",
]

if __name__ == "__main__":
    main()
