# -*- coding: utf-8 -*-
"""Verification logic for external AI Universe multi-agent debate responses (AI Universe Integration)."""

from typing import Any, Dict, List, Optional, Tuple
from friday.core.logging import get_logger

logger = get_logger("core.verification")

_SECURITY_SAFETY_KEYWORDS = {
    "security",
    "vulnerability",
    "breach",
    "exploit",
    "critical",
    "privilege escalation",
    "data loss",
    "injection",
    "unauthorized",
    "danger",
    "malicious",
    "sandbox escape",
}


def evaluate_ai_universe_response(response: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Evaluate an AI Universe response against verification rules.

    Rules:
    1. If confidence < 0.70, reject and return "Needs Human Review".
    2. If unresolved_disagreements contain critical security/safety keywords,
       flag for explicit user authorization.
    3. If confidence >= 0.70 and valid, extract answer, key_evidence, and run_id.

    Returns:
        (is_verified, status_or_reason, extracted_data)
    """
    if not isinstance(response, dict):
        return False, "Invalid response payload format", {}

    confidence = float(response.get("confidence", 0.0) or 0.0)
    answer = str(response.get("answer", "") or "").strip()
    unresolved = response.get("unresolved_disagreements", []) or []
    key_evidence = response.get("key_evidence", []) or []
    run_id = str(response.get("run_id", "") or "")

    extracted_data = {
        "answer": answer,
        "confidence": confidence,
        "unresolved_disagreements": unresolved,
        "key_evidence": key_evidence,
        "run_id": run_id,
    }

    # Rule 2: Security / Safety Disagreements Check
    disagreement_text = " ".join(str(d).lower() for d in unresolved)
    critical_flags = [kw for kw in _SECURITY_SAFETY_KEYWORDS if kw in disagreement_text]
    if critical_flags:
        logger.warning(
            f"AI Universe response has critical security disagreements: {critical_flags} (run_id: {run_id})"
        )
        extracted_data["requires_user_authorization"] = True
        extracted_data["security_flags"] = critical_flags
        return False, f"Flagged for User Authorization: Unresolved safety concerns ({', '.join(critical_flags)})", extracted_data

    # Rule 1: Confidence Gating (< 0.70)
    if confidence < 0.70:
        logger.info(f"AI Universe response confidence below threshold ({confidence:.2f} < 0.70) for run {run_id}")
        return False, "Needs Human Review", extracted_data

    # Rule 3: Verified High Confidence
    return True, "Verified", extracted_data
