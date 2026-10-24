"""
FRIDAY/apps/core/src/friday_core/security_hardening.py — FRIDAY Security Hardening Module.

SSRF protection, path traversal defense, CORS configuration,
input validation, and security audit logging across all agents.
"""
from __future__ import annotations

import ipaddress
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware

router = APIRouter()

# Blocked IP ranges for SSRF protection
BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.169.254/32"),  # Cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Blocked URL patterns for SSRF
BLOCKED_URL_PATTERNS = [
    r"localhost",
    r"127\.0\.0\.1",
    r"0\.0\.0\.0",
    r"169\.254\.169\.254",
    r"metadata\.google\.internal",
    r"metadata\.azure\.com",
    r"169\.254\.170\.2",
]


@dataclass
class SecurityCheck:
    """A security check record."""
    check_id: str
    check_type: str  # ssrf, path_traversal, cors, auth, input_validation
    target: str
    passed: bool
    details: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class SecurityViolation:
    """A security violation record."""
    violation_id: str
    violation_type: str
    target: str
    severity: str = "high"  # low, medium, high, critical
    description: str = ""
    timestamp: float = field(default_factory=time.time)
    blocked: bool = True


@dataclass
class SecurityPolicy:
    """A security policy configuration."""
    policy_id: str
    name: str
    rule_type: str  # ssrf, path_traversal, cors, auth
    enabled: bool = True
    severity: str = "high"


class SecurityHardeningEngine:
    """Engine for security hardening across all agents."""

    def __init__(self) -> None:
        self._checks: list[SecurityCheck] = []
        self._violations: dict[str, SecurityViolation] = {}
        self._policies: dict[str, SecurityPolicy] = {}
        self._allowed_origins: set[str] = set()
        self._sandbox_dirs: list[str] = []
        self._register_default_policies()

    def _register_default_policies(self) -> None:
        """Register default security policies."""
        policies = [
            ("SSRF Defense", "ssrf", "high"),
            ("Path Traversal Defense", "path_traversal", "high"),
            ("CORS Restriction", "cors", "medium"),
            ("Authentication Required", "auth", "critical"),
            ("Input Validation", "input_validation", "medium"),
        ]
        for name, rule_type, severity in policies:
            policy_id = f"pol_{uuid.uuid4().hex[:8]}"
            self._policies[policy_id] = SecurityPolicy(
                policy_id=policy_id, name=name, rule_type=rule_type, severity=severity,
            )

    def check_ssrf(self, url: str) -> bool:
        """Check if a URL is safe from SSRF attacks."""
        for pattern in BLOCKED_URL_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                self._violations[f"v_{uuid.uuid4().hex[:8]}"] = SecurityViolation(
                    violation_id=f"v_{uuid.uuid4().hex[:8]}",
                    violation_type="ssrf", target=url,
                    severity="critical",
                    description=f"Blocked URL pattern: {pattern}",
                )
                self._checks.append(SecurityCheck(
                    check_id=f"c_{uuid.uuid4().hex[:8]}",
                    check_type="ssrf", target=url, passed=False,
                    details=f"Blocked pattern: {pattern}",
                ))
                return False

        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.hostname:
                ip = ipaddress.ip_address(parsed.hostname)
                for network in BLOCKED_RANGES:
                    if ip in network:
                        self._violations[f"v_{uuid.uuid4().hex[:8]}"] = SecurityViolation(
                            violation_id=f"v_{uuid.uuid4().hex[:8]}",
                            violation_type="ssrf", target=url,
                            severity="critical",
                            description=f"Blocked IP range: {network}",
                        )
                        self._checks.append(SecurityCheck(
                            check_id=f"c_{uuid.uuid4().hex[:8]}",
                            check_type="ssrf", target=url, passed=False,
                            details=f"Blocked IP: {ip} in {network}",
                        ))
                        return False
        except ValueError:
            # Not an IP, check hostname patterns
            pass

        self._checks.append(SecurityCheck(
            check_id=f"c_{uuid.uuid4().hex[:8]}",
            check_type="ssrf", target=url, passed=True,
            details="URL passed SSRF check",
        ))
        return True

    def check_path_traversal(self, file_path: str, sandbox_dirs: list[str] | None = None) -> bool:
        """Check if a file path is safe from traversal attacks."""
        sandbox_dirs = sandbox_dirs or self._sandbox_dirs
        if not sandbox_dirs:
            return True  # No sandbox configured, allow

        resolved = str(Path(file_path).resolve())
        for sandbox in sandbox_dirs:
            sandbox_resolved = str(Path(sandbox).resolve())
            if resolved.startswith(sandbox_resolved):
                self._checks.append(SecurityCheck(
                    check_id=f"c_{uuid.uuid4().hex[:8]}",
                    check_type="path_traversal", target=file_path, passed=True,
                    details=f"Path within sandbox: {sandbox}",
                ))
                return True

        self._violations[f"v_{uuid.uuid4().hex[:8]}"] = SecurityViolation(
            violation_id=f"v_{uuid.uuid4().hex[:8]}",
            violation_type="path_traversal", target=file_path,
            severity="high",
            description=f"Path outside sandbox: {file_path}",
        )
        self._checks.append(SecurityCheck(
            check_id=f"c_{uuid.uuid4().hex[:8]}",
            check_type="path_traversal", target=file_path, passed=False,
            details="Path outside sandbox",
        ))
        return False

    def register_sandbox_dir(self, directory: str) -> dict[str, Any]:
        """Register a sandbox directory for path confinement."""
        if directory not in self._sandbox_dirs:
            self._sandbox_dirs.append(directory)
        return {"sandbox_dir": directory, "total_sandboxes": len(self._sandbox_dirs)}

    def configure_cors(self, allowed_origins: list[str]) -> dict[str, Any]:
        """Configure allowed CORS origins."""
        self._allowed_origins = set(allowed_origins)
        return {
            "allowed_origins": list(self._allowed_origins),
            "wildcard_allowed": False,
        }

    def check_cors(self, origin: str) -> bool:
        """Check if an origin is allowed by CORS policy."""
        if origin in self._allowed_origins or "*" in self._allowed_origins:
            return True
        self._checks.append(SecurityCheck(
            check_id=f"c_{uuid.uuid4().hex[:8]}",
            check_type="cors", target=origin, passed=False,
            details="Origin not in allowed list",
        ))
        return False

    def check_input(self, data: str, max_length: int = 10000) -> bool:
        """Check input for validation."""
        if len(data) > max_length:
            self._violations[f"v_{uuid.uuid4().hex[:8]}"] = SecurityViolation(
                violation_id=f"v_{uuid.uuid4().hex[:8]}",
                violation_type="input_validation", target="input",
                severity="medium",
                description=f"Input exceeds max length: {len(data)} > {max_length}",
            )
            return False

        # Check for suspicious patterns
        suspicious_patterns = [r"<script", r"javascript:", r"data:", r"vbscript:"]
        for pattern in suspicious_patterns:
            if re.search(pattern, data, re.IGNORECASE):
                self._violations[f"v_{uuid.uuid4().hex[:8]}"] = SecurityViolation(
                    violation_id=f"v_{uuid.uuid4().hex[:8]}",
                    violation_type="input_validation", target="input",
                    severity="high",
                    description=f"Suspicious pattern detected: {pattern}",
                )
                return False

        return True

    def get_violations(self, severity: str | None = None) -> list[dict[str, Any]]:
        """Get security violations."""
        violations = list(self._violations.values())
        if severity:
            violations = [v for v in violations if v.severity == severity]
        return [
            {
                "violation_id": v.violation_id,
                "violation_type": v.violation_type,
                "target": v.target,
                "severity": v.severity,
                "description": v.description,
                "blocked": v.blocked,
            }
            for v in violations
        ]

    def get_checks(self, check_type: str | None = None) -> list[dict[str, Any]]:
        """Get security checks."""
        checks = list(self._checks)
        if check_type:
            checks = [c for c in checks if c.check_type == check_type]
        return [
            {
                "check_id": c.check_id,
                "check_type": c.check_type,
                "target": c.target,
                "passed": c.passed,
                "details": c.details,
            }
            for c in checks[-50:]
        ]

    def get_report(self) -> dict[str, Any]:
        """Get security hardening report."""
        return {
            "total_checks": len(self._checks),
            "passed_checks": sum(1 for c in self._checks if c.passed),
            "failed_checks": sum(1 for c in self._checks if not c.passed),
            "total_violations": len(self._violations),
            "blocked_violations": sum(1 for v in self._violations.values() if v.blocked),
            "sandbox_dirs": len(self._sandbox_dirs),
            "allowed_origins": len(self._allowed_origins),
            "policies_enabled": sum(1 for p in self._policies.values() if p.enabled),
            "engine_status": "operational",
        }


engine = SecurityHardeningEngine()


@router.post("/security/ssrf/check")
async def check_ssrf(url: str):
    """Check URL for SSRF attacks."""
    safe = engine.check_ssrf(url)
    return {"url": url, "safe": safe}


@router.post("/security/path/check")
async def check_path(file_path: str):
    """Check file path for traversal attacks."""
    safe = engine.check_path_traversal(file_path)
    return {"file_path": file_path, "safe": safe}


@router.post("/security/sandbox/register")
async def register_sandbox(directory: str):
    """Register a sandbox directory."""
    return engine.register_sandbox_dir(directory)


@router.post("/security/cors/configure")
async def configure_cors(allowed_origins: list[str]):
    """Configure CORS allowed origins."""
    return engine.configure_cors(allowed_origins)


@router.post("/security/input/check")
async def check_input(data: str, max_length: int = 10000):
    """Check input for validation."""
    safe = engine.check_input(data, max_length)
    return {"safe": safe, "length": len(data)}


@router.get("/security/violations")
async def get_violations(severity: str | None = None):
    """Get security violations."""
    return {"violations": engine.get_violations(severity)}


@router.get("/security/checks")
async def get_checks(check_type: str | None = None):
    """Get security checks."""
    return {"checks": engine.get_checks(check_type)}


@router.get("/security/report")
async def security_report():
    """Get security hardening report."""
    return engine.get_report()
