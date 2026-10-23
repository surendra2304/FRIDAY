"""Portable FRIDAY verification runner.

The default run executes repository-local tests and a tracked-file security scan.
Live Gemini tests are opt-in because they need real credentials and can incur cost.
This script deliberately never commits or pushes repository changes.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.performance_monitor import monitor_performance  # noqa: E402
from security_check import run_security_check  # noqa: E402


def _run_pytest(marker: str | None = None) -> str:
    """Execute pytest against this checkout, independent of the caller's directory."""
    command = [sys.executable, "-m", "pytest", "-q"]
    if marker:
        command.extend(["-m", marker])
    command.append(str(ROOT / "tests"))

    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout


def run_pytest() -> str:
    """Run the normal offline suite; pytest configuration excludes live and hardware tests."""
    return _run_pytest()


def run_real_gemini_tests() -> str:
    """Run only explicitly marked live tests; callers must opt in via the CLI."""
    return _run_pytest(marker="live")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run FRIDAY's repository verification checks.")
    parser.add_argument(
        "--include-live",
        action="store_true",
        help="also run tests marked 'live' (requires valid provider credentials and may incur API costs)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run verification stages and return a process exit code without Git side effects."""
    args = _parse_args(argv)
    try:
        if not run_security_check(root=ROOT):
            return 1

        print("Running repository test suite...")
        with monitor_performance(name="full_pytest_suite", log_dir=ROOT):
            run_pytest()

        if args.include_live:
            print("Running opted-in live Gemini integration tests...")
            with monitor_performance(name="live_gemini_tests", log_dir=ROOT):
                run_real_gemini_tests()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1

    print("FRIDAY verification completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
