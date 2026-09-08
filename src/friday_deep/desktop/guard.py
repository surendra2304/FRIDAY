from dataclasses import dataclass
from enum import Enum
from ..contracts import Trust


class Decision(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True)
class Action:
    action_type: str
    args: dict
    source: Trust
    requires_confirmation: bool = True


class ComputerGuard:
    HARD = (
        "format c:",
        "diskpart",
        "rm -rf",
        "del /f",
        "rmdir /s",
        "taskkill /f",
        "kill -9",
        "drop database",
        "disable security",
        "export api_key",
        "dump credentials",
        "transfer funds",
        "pay invoice",
    )

    def evaluate(self, a: Action) -> Decision:
        if a.source is Trust.EXTERNAL:
            return Decision.BLOCK
        text = " ".join([a.action_type, *[str(v) for v in a.args.values()]]).lower()
        if any(x in text for x in self.HARD):
            return Decision.BLOCK
        if a.requires_confirmation:
            return Decision.REVIEW
        return Decision.ALLOW
