"""Browser safety guardrails, domain restrictions, and action validation for FRIDAY.

Ensures autonomous browser automation remains strictly confined within configurable
security boundaries, preventing unauthorized navigation, malicious downloads,
and unintended authentication disclosures.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel

logger = get_logger("integrations.browser.safety")


@dataclass
class BrowserSafetyPolicy:
    """Configurable browser safety rules enforced across all browser executors."""

    allowed_domains: list[str] = field(default_factory=list)  # Empty means all non-blocked domains permitted
    blocked_domains: list[str] = field(
        default_factory=lambda: [
            # High-risk financial, darknet, or administrative endpoints unless explicitly allowed
            "bank",
            "paypal.com",
            "stripe.com",
            "login.live.com",
            "accounts.google.com",
            "darkweb",
            "onion",
        ]
    )
    max_steps_per_task: int = 25
    allow_downloads: bool = False
    allow_file_uploads: bool = False
    allow_javascript_execution: bool = True
    enforce_https: bool = False
    max_timeout_seconds: float = 60.0
    require_confirmation_for_external_submits: bool = True


class BrowserSafetyGuard:
    """Validates URLs and browser actions against safety policies."""

    def __init__(self, policy: BrowserSafetyPolicy | None = None) -> None:
        self.policy = policy or BrowserSafetyPolicy()

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Verify if a URL is safe to navigate to."""
        clean_url = (url or "").strip()
        if not clean_url:
            return False, "URL cannot be empty."

        # Ensure scheme
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.scheme not in ("http", "https", "about", "data"):
            return False, f"Unsupported or dangerous URL scheme: '{parsed.scheme}'."

        if self.policy.enforce_https and parsed.scheme == "http":
            return False, "HTTP navigation blocked by HTTPS-only policy."

        hostname = (parsed.hostname or "").lower()

        # Check blocked domains
        for blocked in self.policy.blocked_domains:
            if blocked in hostname:
                logger.warning(f"Navigation blocked to restricted domain: {hostname} (matched '{blocked}')")
                return False, f"Navigation to '{hostname}' is blocked by security policy."

        # Check allowed domains (if whitelist specified)
        if self.policy.allowed_domains:
            allowed = False
            for white in self.policy.allowed_domains:
                if hostname == white.lower() or hostname.endswith(f".{white.lower()}"):
                    allowed = True
                    break
            if not allowed:
                logger.warning(f"Domain not in allowlist: {hostname}")
                return False, f"Domain '{hostname}' is not in the allowed domains list."

        return True, "URL is safe for navigation."

    def sanitize_action(self, action_name: str, parameters: dict[str, Any]) -> tuple[bool, str, SafetyLevel]:
        """Validate an individual browser action (click, type, submit, download)."""
        action = action_name.lower().strip()

        # Check downloads
        if action in ("download", "download_file") and not self.policy.allow_downloads:
            return False, "File downloads are disabled in the current browser safety policy.", SafetyLevel.DANGEROUS

        # Check uploads
        if action in ("upload", "upload_file") and not self.policy.allow_file_uploads:
            return False, "File uploads are disabled in the current browser safety policy.", SafetyLevel.SENSITIVE

        # Sensitive form submission
        if action in ("submit", "click_submit", "confirm_payment"):
            return True, "Submit action requires confirmation.", SafetyLevel.SENSITIVE

        return True, "Action approved.", SafetyLevel.SAFE
