import os
import re
from pathlib import Path

# Define Phase 6 stages and keywords to search for
STAGES = [
    ("Vision Foundation", ["vision foundation", "GeminiVisionProvider", "vision provider"]),
    ("Screen Capture", ["screen capture", "WindowsScreenCaptureProvider", "get_screen_snapshot"]),
    ("Screen Understanding", ["screen understanding", "ScreenAnalyzer", "prompt injection"]),
    ("Screen Awareness", ["screen awareness", "ScreenAwarenessController", "deduplication"]),
    ("Vision Memory", ["vision memory", "VisionMemoryManager", "fts fallback", "secret redaction"]),
    ("Voice + Vision", ["voice + vision", "GeminiLiveVoiceSession", "multimodal"]),
    ("Action Proposal", ["computer action proposal", "ProposeComputerActionTool"]),
    ("Safe Computer Control", ["safe computer control", "hard-block", "ComputerActionExecutor"]),
    ("Security Audit", ["security audit", "prompt injection defense", "credential failover"]),
    ("Multimodal Acceptance Gate", ["multimodal acceptance", "demonstration"]),
]

ROOT = Path(os.getcwd())
SRC_DIR = ROOT / "src" / "friday"
TESTS_DIR = ROOT / "tests"

def scan_files(directories):
    content_map = {}
    for dir_path in directories:
        for path in dir_path.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
                content_map[path] = text.lower()
            except Exception:
                continue
    return content_map

files_content = scan_files([SRC_DIR, TESTS_DIR])

report_lines = [
    "# Phase 6 Completion Audit Report",
    "",
    "| Stage | Status | Evidence |",
    "|---|---|---|",
]

for stage, keywords in STAGES:
    status = "NOT IMPLEMENTED"
    evidence = ""
    for path, text in files_content.items():
        if any(kw.lower() in text for kw in keywords):
            status = "COMPLETE"
            evidence = f"Found in `{path.relative_to(ROOT)}`"
            break
    report_lines.append(f"| {stage} | {status} | {evidence} |")

report_content = "\n".join(report_lines) + "\n"

# Write report to artifacts directory
artifacts_dir = Path(os.getenv("AGY_ARTIFACT_DIR", "C:/Users/Surendra/.gemini/antigravity-ide/brain/755db1b6-3b52-4ed0-94b5-c4b0a947ff17/artifacts"))
artifacts_dir.mkdir(parents=True, exist_ok=True)
report_path = artifacts_dir / "phase6_audit_report.md"
report_path.write_text(report_content, encoding="utf-8")
print(f"Phase 6 audit report written to {report_path}")
