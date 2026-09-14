from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import Trust
from ..security.redaction import DEFAULT, SecretRedactor


@dataclass
class Record:
    key: str
    content: str
    trust: Trust = Trust.SYSTEM
    metadata: dict[str, Any] = field(default_factory=dict)


class EphemeralStore:
    """In-memory store with automatic secret redaction on persistence."""

    def __init__(self, redactor: SecretRedactor | None = None) -> None:
        self._store: dict[str, Record] = {}
        self.redactor = redactor or DEFAULT

    def put(self, record: Record) -> None:
        redacted_content = self.redactor.redact(record.content) or ""
        self._store[record.key] = Record(
            key=record.key,
            content=redacted_content,
            trust=record.trust,
            metadata=dict(record.metadata),
        )

    def get(self, key: str) -> Record | None:
        return self._store.get(key)

    def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def list(self) -> list[Record]:
        return list(self._store.values())

    def clear(self) -> None:
        self._store.clear()
