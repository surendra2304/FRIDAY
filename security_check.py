# -*- coding: utf-8 -*-
"""Repository secret scanner used by the CLI and verification workflow.

The scanner examines tracked files only, so ignored local credentials are never
read or printed. Findings report paths and secret categories, never secret values.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent

SECRET_PATTERNS = [
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "Google Gemini / Firebase API Key"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), "OpenAI Secret Key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b"), "GitHub Personal Access Token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9_-]{10,}\b"), "Slack Token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
    (re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PRIVATE) KEY-----"), "Private Key Header"),
    (
        re.compile(
            r"bearer\s+eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.?[A-Za-z0-9\-_.+/=]*",
            re.IGNORECASE,
        ),
        "Bearer JWT Token",
    ),
    (
        re.compile(r"(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^\s/]+", re.IGNORECASE),
        "Database Connection URI with Credentials",
    ),
]

SAFE_TEST_TOKENS = {
    "SECRET_TOKEN_12345",
    "mock_key",
    "test_key",
    "dummy_key",
    "fake_key",
    "hash_abc",
    "hash_xyz",
    "env_hash_original",
    "env_hash_different",
}
_SCANNER_FILES = {
    "security_check.py",
    "scripts/security_check.py",
    "scripts/phase6_audit.py",
    "tests/test_security_check.py",
}


def _tracked_files(root: str | Path = ROOT) -> list[str]:
    """Return tracked repository paths; fail closed if Git cannot inspect them."""
    root_path = Path(root).resolve()
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "git ls-files failed"
        raise RuntimeError(f"Cannot inspect tracked files under {root_path}: {message}")
    return [path for path in result.stdout.split("\0") if path]


def git_ls_env(root: str | Path = ROOT) -> List[str]:
    """Return tracked .env and .env.* files (the result must be empty)."""
    return [
        path
        for path in _tracked_files(root)
        if Path(path).name == ".env" or Path(path).name.startswith(".env.")
    ]


def is_safe_test_fixture(file_path: str, line: str, match_text: str) -> bool:
    """Avoid flagging intentionally synthetic credentials in tests."""
    normalized_path = file_path.replace("\\", "/").lower()
    if not normalized_path.startswith("tests/"):
        return False

    if match_text in SAFE_TEST_TOKENS or match_text.strip("'\"") in SAFE_TEST_TOKENS:
        return True

    lower_line = line.lower()
    lower_match = match_text.lower()
    mock_indicators = (
        "mock",
        "test",
        "dummy",
        "fake",
        "example",
        "sample",
        "neverleak",
        "secret-key",
        "12345",
        "abcdef",
        "zyxwvu",
        "scrub",
        "redact",
        "fixture",
        "raw_secret",
        "dummy_key",
        "secret_key",
    )
    return any(indicator in lower_match or indicator in lower_line for indicator in mock_indicators)


def scan_for_real_secrets(root: str | Path = ROOT) -> List[Tuple[str, int, str]]:
    """Scan tracked UTF-8 files and return (path, line, category) without secret values."""
    root_path = Path(root).resolve()
    findings: List[Tuple[str, int, str]] = []
    for relative_path in _tracked_files(root_path):
        if relative_path in _SCANNER_FILES:
            continue
        try:
            with (root_path / relative_path).open("r", encoding="utf-8", errors="ignore") as source:
                for line_number, line in enumerate(source, start=1):
                    for pattern, secret_type in SECRET_PATTERNS:
                        match = pattern.search(line)
                        if match and not is_safe_test_fixture(relative_path, line, match.group(0)):
                            findings.append((relative_path, line_number, secret_type))
        except (OSError, UnicodeError):
            # Binary files and files removed between git enumeration and open are ignored.
            continue
    return findings


def run_security_check(
    root: str | Path = ROOT,
    report_path: str | Path | None = None,
) -> bool:
    """Run the tracked-file security check and write a report only on success."""
    root_path = Path(root).resolve()
    env_files = git_ls_env(root_path)
    if env_files:
        print("[!] CRITICAL: Tracked environment files found in git:")
        for path in env_files:
            print(f"    - {path}")
        return False

    findings = scan_for_real_secrets(root_path)
    if findings:
        print("[!] CRITICAL: Potential hardcoded credentials found in tracked files:")
        for path, line_number, category in findings:
            print(f"    - {path}: line {line_number} [{category}]")
        return False

    destination = Path(report_path) if report_path is not None else root_path / "security_report.txt"
    if not destination.is_absolute():
        destination = root_path / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "FRIDAY security check PASSED: no tracked environment files or secret patterns found.\n",
        encoding="utf-8",
    )
    print("[+] PASS: no tracked environment files or secret patterns found.")
    return True


def main() -> None:
    """CLI entrypoint; use a non-zero exit code on findings or inspection errors."""
    try:
        clean = run_security_check()
    except RuntimeError as exc:
        print(f"[!] Security scan could not complete: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if not clean:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
