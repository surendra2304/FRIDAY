# -*- coding: utf-8 -*-
"""Comprehensive security auditing tool for FRIDAY.

Detects real API keys, bearer tokens, private keys, database URLs, and credentials
while distinguishing legitimate code symbols, test hashes, and markdown formatting.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Patterns for actual secrets (API keys, private keys, JWT, passwords)
SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google Gemini / Firebase API Key"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,T3BlbkFJ[a-zA-Z0-9]{20,}"), "OpenAI Secret Key"),
    (re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PRIVATE) KEY-----"), "Private Key Header"),
    (re.compile(r"bearer\s+eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_.+/=]*", re.IGNORECASE), "Bearer JWT Token"),
    (re.compile(r"(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^\s/]+", re.IGNORECASE), "Database Connection URI with Credentials"),
]

# Paths allowed to contain test fixtures / mock tokens (must still not contain REAL keys)
SAFE_TEST_TOKENS = {
    "SECRET_TOKEN_12345", "mock_key", "test_key", "dummy_key", "fake_key",
    "hash_abc", "hash_xyz", "env_hash_original", "env_hash_different"
}


def git_ls_env() -> List[str]:
    """Return list of tracked .env files (must be strictly empty)."""
    result = subprocess.run(["git", "ls-files", ".env"], capture_output=True, text=True)
    return [f for f in result.stdout.strip().splitlines() if f]


def scan_for_real_secrets() -> List[Tuple[str, int, str]]:
    """Scan all tracked files in git repository for genuine hardcoded secrets."""
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    files = [f for f in result.stdout.strip().splitlines() if f]
    findings = []

    for f in files:
        # Ignore security scanning scripts themselves
        if f in ("security_check.py", "scripts/phase6_audit.py"):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, start=1):
                    for pattern, secret_type in SECRET_PATTERNS:
                        if pattern.search(line):
                            findings.append((f, i, secret_type))
        except Exception:
            continue
    return findings


def main():
    print("[*] Running FRIDAY Phase 10.2 Comprehensive Security Audit...")
    env_files = git_ls_env()
    if env_files:
        print("[!] CRITICAL: Tracked .env files found in git:")
        for f in env_files:
            print(f"    - {f}")
        sys.exit(1)

    secret_matches = scan_for_real_secrets()
    if secret_matches:
        print("[!] CRITICAL: Genuine hardcoded secret patterns found in tracked files:")
        for f, line_no, s_type in secret_matches:
            print(f"    - {f}: line {line_no} [{s_type}]")
        sys.exit(1)

    print("[+] PASS: Zero tracked .env files and zero genuine hardcoded secrets found.")
    with open("security_report.txt", "w", encoding="utf-8") as out:
        out.write("Phase 10.2 Security check PASSED. Zero tracked .env files and zero real secrets detected.\n")


if __name__ == "__main__":
    main()
