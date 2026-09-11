"""AgentShield Security Engine for FRIDAY (Adapted from ECC AgentShield).

Provides automated security scanning for:
1. Prompt injection, jailbreak attempts, and instruction hijacking.
2. Hardcoded API keys, JWTs, private keys, and credential leaks.
3. Tool capability misconfigurations and unsafe execution boundaries.
4. Repository and configuration security hygiene.
"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("security.agent_shield")


class SecuritySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class SecurityFinding:
    """Individual security vulnerability or misconfiguration finding."""
    rule_id: str
    title: str
    description: str
    severity: SecuritySeverity
    target: str = ""
    line: int | None = None
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "target": self.target,
            "line": self.line,
            "remediation": self.remediation,
        }


@dataclass
class SecurityAuditReport:
    """Consolidated security audit report produced by AgentShield."""
    findings: list[SecurityFinding] = field(default_factory=list)
    targets_scanned: int = 0
    scanned_path: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.LOW)

    @property
    def grade(self) -> str:
        """Calculate letter grade based on findings."""
        if self.critical_count > 0:
            return "F"
        if self.high_count > 2:
            return "D"
        if self.high_count > 0 or self.medium_count > 3:
            return "C"
        if self.medium_count > 0 or self.low_count > 5:
            return "B"
        return "A"

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_path": self.scanned_path,
            "targets_scanned": self.targets_scanned,
            "grade": self.grade,
            "counts": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
                "total": len(self.findings),
            },
            "findings": [f.to_dict() for f in self.findings],
        }

    def format_summary(self) -> str:
        """Format an executive text summary of the audit."""
        lines = [
            "🛡️ AGENTSHIELD AUDIT REPORT",
            "============================",
            f"Security Grade:  [{self.grade}]",
            f"Targets Scanned: {self.targets_scanned}",
            f"Total Findings:  {len(self.findings)}",
            f"  - 🚨 Critical: {self.critical_count}",
            f"  - 🔴 High:     {self.high_count}",
            f"  - 🟡 Medium:   {self.medium_count}",
            f"  - 🔵 Low:      {self.low_count}",
            "",
        ]
        if not self.findings:
            lines.append("✅ No security vulnerabilities detected. System is secure.")
        else:
            lines.append("Key Findings:")
            for idx, f in enumerate(self.findings[:10], 1):
                lines.append(f"  {idx}. [{f.severity.value}] {f.title} ({f.target})")
                if f.remediation:
                    lines.append(f"     Fix: {f.remediation}")
            if len(self.findings) > 10:
                lines.append(f"  ... and {len(self.findings) - 10} more.")
        return "\n".join(lines)


class AgentShield:
    """Core security analysis engine for FRIDAY and its agent environment."""

    # Common secret detection regexes
    SECRET_PATTERNS: list[tuple[str, str, SecuritySeverity, re.Pattern[str]]] = [
        (
            "SEC-001",
            "Google API Key Exposure",
            SecuritySeverity.CRITICAL,
            re.compile(r"AIzaSy[A-Za-z0-9_-]{33}"),
        ),
        (
            "SEC-002",
            "OpenAI API Key Exposure",
            SecuritySeverity.CRITICAL,
            re.compile(r"sk-[a-zA-Z0-9]{20,}"),
        ),
        (
            "SEC-003",
            "Anthropic API Key Exposure",
            SecuritySeverity.CRITICAL,
            re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),
        ),
        (
            "SEC-004",
            "Groq API Key Exposure",
            SecuritySeverity.CRITICAL,
            re.compile(r"gsk_[a-zA-Z0-9]{30,}"),
        ),
        (
            "SEC-005",
            "GitHub Personal Access Token Exposure",
            SecuritySeverity.HIGH,
            re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}|github_pat_[A-Za-z0-9_]{82}"),
        ),
        (
            "SEC-006",
            "AWS Access Key ID Exposure",
            SecuritySeverity.HIGH,
            re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        ),
        (
            "SEC-007",
            "Private RSA/SSH Key Exposure",
            SecuritySeverity.CRITICAL,
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        ),
        (
            "SEC-008",
            "Generic Hardcoded Password / Secret Assignment",
            SecuritySeverity.MEDIUM,
            re.compile(r'(?:api_key|secret_key|password|auth_token)\s*=\s*["\'][^"\']{8,}["\']', re.IGNORECASE),
        ),
    ]

    # Prompt injection patterns
    INJECTION_PATTERNS: list[tuple[str, str, SecuritySeverity, re.Pattern[str]]] = [
        (
            "INJ-001",
            "Instruction Override / Jailbreak Vector",
            SecuritySeverity.CRITICAL,
            re.compile(
                r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|system\s+instructions)",
                re.IGNORECASE,
            ),
        ),
        (
            "INJ-002",
            "System Delimiter Breakout Attempt",
            SecuritySeverity.HIGH,
            re.compile(r"(?:</(?:thought|instruction|system|context)>|\[SYSTEM\]|\[INST\])", re.IGNORECASE),
        ),
        (
            "INJ-003",
            "DAN / Developer Persona Hijack",
            SecuritySeverity.HIGH,
            re.compile(r"\b(?:DAN\s+mode|developer\s+mode\s+enabled|always\s+say\s+yes|jailbreak)\b", re.IGNORECASE),
        ),
        (
            "INJ-004",
            "Environment Credential Exfiltration Request",
            SecuritySeverity.CRITICAL,
            re.compile(
                r"(?:print|echo|curl|fetch|cat)\s+.*(?:\.env|os\.environ|environment_variables|API_KEY)",
                re.IGNORECASE,
            ),
        ),
    ]

    def scan_prompt(self, prompt: str, target: str = "prompt") -> list[SecurityFinding]:
        """Scan a user prompt or agent input for prompt injection vectors."""
        findings: list[SecurityFinding] = []
        if not prompt:
            return findings

        for rule_id, title, severity, pattern in self.INJECTION_PATTERNS:
            if pattern.search(prompt):
                findings.append(
                    SecurityFinding(
                        rule_id=rule_id,
                        title=title,
                        description=f"Prompt matches adversarial pattern: '{rule_id}'.",
                        severity=severity,
                        target=target,
                        remediation="Sanitize external input, filter delimiters, or quarantine request.",
                    )
                )

        return findings

    def scan_text_for_secrets(self, content: str, target: str = "") -> list[SecurityFinding]:
        """Scan text or code content for exposed credentials and secrets."""
        findings: list[SecurityFinding] = []
        if not content:
            return findings

        # Skip example/dummy files
        if "example" in target.lower() or "test" in target.lower() and "dummy" in content.lower():
            return findings

        lines = content.splitlines()
        for rule_id, title, severity, pattern in self.SECRET_PATTERNS:
            for idx, line in enumerate(lines, 1):
                # Ignore comment placeholders or dummy values
                if any(mock_word in line.lower() for mock_word in ["example", "your_key", "dummy", "placeholder", "fake"]):
                    continue
                if pattern.search(line):
                    findings.append(
                        SecurityFinding(
                            rule_id=rule_id,
                            title=title,
                            description=f"Potential active secret matched by pattern '{rule_id}'.",
                            severity=severity,
                            target=target,
                            line=idx,
                            remediation="Move secret to environment variable (.env) and add to .gitignore.",
                        )
                    )

        return findings

    def scan_tool(self, tool_name: str, tool_obj: Any) -> list[SecurityFinding]:
        """Audit a registered tool for dangerous permissions and capability declarations."""
        findings: list[SecurityFinding] = []
        safety_level = getattr(tool_obj, "safety_level", None)
        safety_val = getattr(safety_level, "value", str(safety_level)).lower()
        desc = getattr(tool_obj, "description", "").lower()

        # Check for dangerous keywords in SAFE tools
        high_risk_words = ["shell", "execute", "command", "delete", "remove", "terminal", "kill", "eval"]
        if safety_val in ["safe", "none"] and any(kw in desc or kw in tool_name.lower() for kw in high_risk_words):
            findings.append(
                SecurityFinding(
                    rule_id="TOOL-001",
                    title="Overly Permissive Tool Safety Level",
                    description=f"Tool '{tool_name}' performs destructive/system operations but is marked as SAFE.",
                    severity=SecuritySeverity.HIGH,
                    target=f"tool:{tool_name}",
                    remediation="Elevate tool safety_level to SENSITIVE or DANGEROUS with mandatory authorization.",
                )
            )

        return findings

    def audit_directory(
        self,
        directory_path: str,
        max_files: int = 200,
        extensions: tuple[str, ...] = (".py", ".json", ".yaml", ".yml", ".md", ".env"),
    ) -> SecurityAuditReport:
        """Scan a directory for secret leaks, unsafe patterns, and configuration vulnerabilities."""
        report = SecurityAuditReport(scanned_path=directory_path)
        base_path = Path(directory_path)

        if not base_path.exists() or not base_path.is_dir():
            return report

        scanned = 0
        ignored_dirs = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv", ".idea"}

        for root, dirs, files in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for file in files:
                if scanned >= max_files:
                    break
                if file.endswith(extensions):
                    file_path = Path(root) / file
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        scanned += 1
                        findings = self.scan_text_for_secrets(content, target=str(file_path.relative_to(base_path)))
                        report.findings.extend(findings)
                    except Exception as err:
                        logger.debug(f"Could not read file {file_path}: {err}")

        report.targets_scanned = scanned
        return report
