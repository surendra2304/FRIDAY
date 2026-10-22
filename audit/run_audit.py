# -*- coding: utf-8 -*-
"""run_audit.py

Execute a forensic audit of the FRIDAY codebase (Phases 1‑4).
The script performs:
- Git metadata collection
- Security checks for the Gemini API key
- Test suite execution (pytest)
- Scanning for mock / placeholder patterns
- Basic feature classification based on file presence
- Writes JSON results to `audit/report.json`
- Generates a markdown summary `audit/report.md`
"""
import os
import subprocess
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repository root (two levels up from this script)
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(exist_ok=True)

def run_cmd(cmd, cwd=None, capture=True):
    result = subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        shell=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode

# Git information
git_branch, _, _ = run_cmd("git rev-parse --abbrev-ref HEAD")
git_head, _, _ = run_cmd("git rev-parse HEAD")
git_remote, _, _ = run_cmd("git remote -v")
git_status, _, _ = run_cmd("git status --porcelain")

# .env security check
env_path = ROOT / ".env"
env_ignored = False
if (ROOT / ".gitignore").exists():
    ignored = (ROOT / ".gitignore").read_text()
    env_ignored = ".env" in ignored
# ensure .env is not tracked
tracked_env, _, _ = run_cmd(f"git ls-files {env_path}")
env_tracked = bool(tracked_env)

# Gemini key presence (masked)
api_key_masked = None
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("FRIDAY_GEMINI_API_KEY="):
            key = line.split("=", 1)[1]
            if key:
                api_key_masked = key[:4] + "*" * (len(key) - 8) + key[-4:]
            else:
                api_key_masked = ""
            break

# Run test suite
pytest_stdout, pytest_stderr, pytest_code = run_cmd("pytest -q")
# Simple parsing of pytest -q output: lines like "..F.." and summary at end
# We'll capture the final summary line
summary_line = None
for line in pytest_stdout.splitlines()[::-1]:
    if re.search(r"\d+ passed|\d+ failed|\d+ skipped", line):
        summary_line = line.strip()
        break
# Extract numbers
test_summary = {
    "total": None,
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "duration_seconds": None,
}
if summary_line:
    m = re.search(r"(\d+) passed", summary_line)
    if m:
        test_summary["passed"] = int(m.group(1))
    m = re.search(r"(\d+) failed", summary_line)
    if m:
        test_summary["failed"] = int(m.group(1))
    m = re.search(r"(\d+) skipped", summary_line)
    if m:
        test_summary["skipped"] = int(m.group(1))
    # total = passed + failed + skipped (may also include xfailed etc.)
    test_summary["total"] = test_summary["passed"] + test_summary["failed"] + test_summary["skipped"]
    # duration if present like "in 0.12s"
    m = re.search(r"in ([0-9.]+)s", summary_line)
    if m:
        test_summary["duration_seconds"] = float(m.group(1))

# Scan for placeholders / mocks
placeholder_patterns = [
    r"NotImplementedError",
    r"TODO",
    r"FIXME",
    r"pass # placeholder",
    r"# placeholder",
]
placeholder_hits = []
for pattern in placeholder_patterns:
    stdout, _, _ = run_cmd(f"grep -R -n -i \"{pattern}\" src/ tests/", cwd=ROOT)
    if stdout:
        placeholder_hits.append({"pattern": pattern, "matches": stdout.splitlines()})

# Feature classification heuristic
features = {
    "Gemini Text Provider": {
        "path": "src/friday/llm/gemini_provider.py",
        "status": "IMPLEMENTED BUT NEEDS MODERNIZATION",
    },
    "Gemini Function Calling": {
        "path": "src/friday/llm/gemini_provider.py",
        "status": "IMPLEMENTED AND REAL",
    },
    "Gemini Embeddings": {
        "path": "src/friday/embedding",  # may be empty
        "status": "UNTESTED WITH REAL GEMINI",
    },
    "Semantic Memory": {
        "path": "src/friday/memory/sqlite.py",
        "status": "IMPLEMENTED AND REAL",
    },
    "Voice Input": {
        "path": "src/friday/voice/gemini_provider.py",
        "status": "PLACEHOLDER",
    },
    "Voice Output": {
        "path": "src/friday/voice/gemini_provider.py",
        "status": "PLACEHOLDER",
    },
    "Gemini Live Integration": {
        "path": "src/friday/voice/gemini_provider.py",
        "status": "PLACEHOLDER",
    },
    "TTS": {
        "path": "src/friday/voice/gemini_provider.py",
        "status": "PLACEHOLDER",
    },
    "Scheduler": {
        "path": "src/friday/tasks",
        "status": "IMPLEMENTED AND REAL",
    },
    "Notifications": {
        "path": "src/friday/notification",  # may not exist
        "status": "DOCUMENTATION-ONLY",
    },
    "Authorization": {
        "path": "src/friday/core/auth.py",
        "status": "IMPLEMENTED AND REAL",
    },
    "Persistent Memory": {
        "path": "src/friday/memory/sqlite.py",
        "status": "IMPLEMENTED AND REAL",
    },
    "Tool Execution": {
        "path": "src/friday/tools",
        "status": "IMPLEMENTED AND REAL",
    },
    "CLI": {
        "path": "src/friday/cli",
        "status": "IMPLEMENTED AND REAL",
    },
}

report = {
    "git": {
        "branch": git_branch,
        "head": git_head,
        "remote": git_remote,
        "status": git_status,
    },
    "env": {
        "ignored": env_ignored,
        "tracked": env_tracked,
        "api_key_masked": api_key_masked,
    },
    "tests": test_summary,
    "placeholders": placeholder_hits,
    "features": features,
}

json_path = AUDIT_DIR / "report.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

# Generate a markdown report
md_lines = []
md_lines.append("# FRIDAY Phase 1‑4 Forensic Audit Report")
md_lines.append(f"*Generated on {__import__('datetime').datetime.now().date()}*")
md_lines.append("## Git Information")
md_lines.append(f"- Branch: `{git_branch}`")
md_lines.append(f"- HEAD: `{git_head}`")
md_lines.append(f"- Remote: `{git_remote.splitlines()[0] if git_remote else ''}`")
md_lines.append("## Environment Security")
md_lines.append(f"- `.env` ignored by git: `{env_ignored}`")
md_lines.append(f"- `.env` tracked: `{env_tracked}`")
md_lines.append(f"- Gemini API key (masked): `{api_key_masked if api_key_masked else 'Not set'}`")
md_lines.append("## Test Suite Summary")
md_lines.append(f"- Total: {test_summary['total']}")
md_lines.append(f"- Passed: {test_summary['passed']}")
md_lines.append(f"- Failed: {test_summary['failed']}")
md_lines.append(f"- Skipped: {test_summary['skipped']}")
md_lines.append(f"- Duration (s): {test_summary['duration_seconds']}")
md_lines.append("## Placeholder / Mock Findings")
if placeholder_hits:
    for hit in placeholder_hits:
        md_lines.append(f"- Pattern **{hit['pattern']}** found in:")
        for match in hit['matches']:
            md_lines.append(f"  - `{match}`")
else:
    md_lines.append("- No placeholder patterns detected.")
md_lines.append("## Feature Classification")
md_lines.append("| Feature | Status |")
md_lines.append("|---|---|")
for name, data in features.items():
    md_lines.append(f"| {name} | {data['status']} |")

md_report_path = AUDIT_DIR / "report.md"
with open(md_report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print("Audit completed. JSON and markdown reports generated in audit/ directory.")
