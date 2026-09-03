"""Workspace security guardrails and command policy for software engineering executors.

Prevents autonomous coding agents from escaping designated project directories,
running destructive operating system commands, or altering files outside the allowed
repository boundaries.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel

logger = get_logger("integrations.mini_swe.safety")


class CodingWorkspaceGuard:
    """Enforces directory confinement and command restrictions on coding agents."""

    DANGEROUS_COMMAND_PATTERNS = [
        "format ",
        "rmdir /s /q c:",
        "rmdir /s /q \\",
        "del /f /s /q c:",
        "rm -rf /",
        ":(){ :|:& };:",
        "curl | sh",
        "curl | bash",
        "wget | sh",
        "dd if=/dev/",
        "mkfs",
        "shutdown",
        "reboot",
        "drop database",
    ]

    DESTRUCTIVE_GIT_ACTIONS = [
        "git reset --hard",
        "git push --force",
        "git clean -fdx",
        "git branch -D",
    ]

    def __init__(self, allowed_roots: list[str | Path] | None = None) -> None:
        if allowed_roots:
            self.allowed_roots = [Path(p).resolve() for p in allowed_roots]
        else:
            # Default to current workspace directory (FRIDAY root)
            self.allowed_roots = [Path(os.getcwd()).resolve()]

    def is_path_allowed(self, target_path: str | Path) -> bool:
        """Verify that a path lies inside one of the authorized workspace roots."""
        try:
            resolved = Path(target_path).resolve()
            return any(
                resolved == root or root in resolved.parents
                for root in self.allowed_roots
            )
        except Exception:
            return False

    def validate_command(self, command: str) -> tuple[bool, str, SafetyLevel]:
        """Verify that a terminal command is safe to execute."""
        cmd_lower = (command or "").strip().lower()

        # Check dangerous command patterns
        for pattern in self.DANGEROUS_COMMAND_PATTERNS:
            if pattern in cmd_lower:
                logger.warning(f"Blocked dangerous command matching pattern: '{pattern}'")
                return False, f"Command contains forbidden pattern '{pattern}'.", SafetyLevel.DANGEROUS

        # Check destructive git commands
        for destructive in self.DESTRUCTIVE_GIT_ACTIONS:
            if destructive in cmd_lower:
                return True, f"Destructive git action '{destructive}' requires user confirmation.", SafetyLevel.SENSITIVE

        return True, "Command approved.", SafetyLevel.SAFE

    def validate_file_modification(self, filepath: str | Path) -> tuple[bool, str]:
        """Ensure file write operations are strictly confined within allowed roots."""
        if not self.is_path_allowed(filepath):
            return False, f"Modification blocked: '{filepath}' is outside authorized workspace boundaries."
        return True, "File modification allowed."
