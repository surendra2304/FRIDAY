"""Continuous Learning v2 - Instinct-Based Architecture for FRIDAY.

Adapted from ECC Continuous Learning v2.1.
Turns session executions, user corrections, and error resolutions into atomic,
confidence-scored "instincts" that guide future planning and execution.
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("learning.instinct_engine")


@dataclass
class Instinct:
    """An atomic learned behavior with confidence scoring and evidence backing."""
    id: str
    trigger: str
    action: str
    confidence: float = 0.5  # Clamped between 0.3 and 0.9
    domain: str = "general"   # code-style, testing, security, debugging, git, workflow
    scope: str = "project"    # project or global
    evidence: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def reinforce(self, evidence_note: str = "", delta: float = 0.1) -> None:
        """Increase confidence upon successful application."""
        self.confidence = min(0.9, round(self.confidence + delta, 2))
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if evidence_note:
            self.evidence.append(f"[{self.updated_at}] Reinforced: {evidence_note}")

    def penalize(self, evidence_note: str = "", delta: float = 0.15) -> None:
        """Decrease confidence upon failed application or contradiction."""
        self.confidence = max(0.3, round(self.confidence - delta, 2))
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if evidence_note:
            self.evidence.append(f"[{self.updated_at}] Penalized: {evidence_note}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instinct":
        return cls(
            id=data["id"],
            trigger=data["trigger"],
            action=data["action"],
            confidence=float(data.get("confidence", 0.5)),
            domain=data.get("domain", "general"),
            scope=data.get("scope", "project"),
            evidence=list(data.get("evidence", [])),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


class InstinctEngine:
    """Manages creation, reinforcement, recall, and persistence of behavioral instincts."""

    def __init__(self, storage_path: str | None = None) -> None:
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            # Default to data/instincts.json inside repository or home dir
            self.storage_path = Path("data/instincts.json")
        self._instincts: dict[str, Instinct] = {}
        self.load()

    def register_instinct(self, instinct: Instinct) -> None:
        """Add or update an instinct in the registry."""
        self._instincts[instinct.id] = instinct
        self.save()

    def learn_from_feedback(
        self,
        trigger: str,
        action: str,
        domain: str = "general",
        outcome: str = "success",
        evidence_note: str = "",
        scope: str = "project",
    ) -> Instinct:
        """Synthesize or update an instinct based on an execution outcome or user correction."""
        instinct_id = self._generate_id(domain, trigger)

        if instinct_id in self._instincts:
            instinct = self._instincts[instinct_id]
            if outcome.lower() in ("success", "pass", "resolved"):
                instinct.reinforce(evidence_note=evidence_note or "Repeated success pattern observed.")
            else:
                instinct.penalize(evidence_note=evidence_note or "Correction or failure reported.")
        else:
            initial_conf = 0.6 if outcome.lower() in ("success", "pass", "resolved") else 0.4
            notes = [f"Initial observation ({outcome}): {evidence_note}"] if evidence_note else []
            instinct = Instinct(
                id=instinct_id,
                trigger=trigger.strip(),
                action=action.strip(),
                confidence=initial_conf,
                domain=domain.strip().lower(),
                scope=scope,
                evidence=notes,
            )
            self._instincts[instinct_id] = instinct

        self.save()
        logger.info(f"Instinct updated: {instinct.id} (confidence: {instinct.confidence})")
        return instinct

    def recall_instincts(
        self,
        context: str,
        domain: str | None = None,
        min_confidence: float = 0.4,
    ) -> list[Instinct]:
        """Find matching instincts for a given context and domain."""
        clean_ctx = context.lower()
        matched: list[Instinct] = []

        ctx_words = set(re.findall(r"\w+", clean_ctx))

        for instinct in self._instincts.values():
            if instinct.confidence < min_confidence:
                continue
            if domain and instinct.domain != domain.lower():
                continue

            # Check keyword intersection with trigger and action
            trigger_words = set(re.findall(r"\w+", instinct.trigger.lower()))
            if not trigger_words:
                continue

            if instinct.trigger.lower() in clean_ctx:
                matched.append(instinct)
                continue

            # Stem matching: check if root of trigger word appears in context
            matches = 0
            for tw in trigger_words:
                stem = tw[:4] if len(tw) >= 4 else tw
                if any(cw.startswith(stem) or stem in cw for cw in ctx_words):
                    matches += 1

            if matches / len(trigger_words) >= 0.4:
                matched.append(instinct)


        # Sort by confidence descending
        matched.sort(key=lambda x: x.confidence, reverse=True)
        return matched

    def format_guidelines_for_prompt(self, instincts: list[Instinct]) -> str:
        """Format recalled instincts into actionable prompt guidelines."""
        if not instincts:
            return ""

        lines = ["\n[Learned Behavioral Instincts]:"]
        for idx, inst in enumerate(instincts[:5], 1):
            lines.append(f"{idx}. ({inst.domain.upper()}) When {inst.trigger} -> {inst.action} [confidence: {inst.confidence}]")
        return "\n".join(lines) + "\n"

    def list_instincts(self, domain: str | None = None) -> list[Instinct]:
        """List all instincts, optionally filtered by domain."""
        insts = list(self._instincts.values())
        if domain:
            insts = [i for i in insts if i.domain == domain.lower()]
        insts.sort(key=lambda x: x.confidence, reverse=True)
        return insts

    def export_to_json(self, export_path: str) -> bool:
        """Export all instincts to a target JSON file."""
        try:
            target = Path(export_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = [i.to_dict() for i in self._instincts.values()]
            target.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception as err:
            logger.error(f"Failed to export instincts to {export_path}: {err}")
            return False

    def import_from_json(self, import_path: str, merge: bool = True) -> int:
        """Import instincts from a JSON file. Returns count of imported instincts."""
        try:
            target = Path(import_path)
            if not target.exists():
                return 0
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return 0

            count = 0
            if not merge:
                self._instincts.clear()

            for item in raw:
                try:
                    inst = Instinct.from_dict(item)
                    self._instincts[inst.id] = inst
                    count += 1
                except Exception:
                    continue

            self.save()
            return count
        except Exception as err:
            logger.error(f"Failed to import instincts from {import_path}: {err}")
            return 0

    def load(self) -> None:
        """Load instincts from local disk."""
        if not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    try:
                        inst = Instinct.from_dict(item)
                        self._instincts[inst.id] = inst
                    except Exception:
                        continue
        except Exception as err:
            logger.warning(f"Could not load instincts from {self.storage_path}: {err}")

    def save(self) -> None:
        """Atomically persist instincts to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [i.to_dict() for i in self._instincts.values()]
            temp_path = self.storage_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_path.replace(self.storage_path)
        except Exception as err:
            logger.warning(f"Could not persist instincts to {self.storage_path}: {err}")

    def _generate_id(self, domain: str, trigger: str) -> str:
        """Generate a deterministic, clean slug ID."""
        clean_trig = re.sub(r"[^\w\s-]", "", trigger.lower())
        slug = re.sub(r"[\s_]+", "-", clean_trig).strip("-")[:40]
        return f"{domain.lower()}-{slug}"
