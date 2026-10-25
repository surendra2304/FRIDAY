"""
FRIDAY/apps/core/src/friday_core/real_harness_engineering.py — Real Harness Engine.

Harness engineering is the discipline of building the scaffolding *around* the
model: the loop that lets it act, the context budget it reasons inside, the
tools and permissions it may use, the checks that decide whether its work is
actually done, and the traces that make all of it debuggable.

This module is a working implementation of those primitives for FRIDAY:

- estimate_tokens / ContextBudget / Message: token accounting for a real window
- ContextCompactor: truncate, sliding-window, extractive-summary and
  hierarchical compaction with measured retention
- Subtask / Plan / TaskDecomposer: dependency graphs, topological order,
  parallel batches, critical path and budget-batched scheduling
- ParamSpec / ToolSpec / ToolRegistry: typed tool schemas, argument
  validation/coercion and guarded dispatch
- PermissionRule / PermissionGate / HumanApprovalQueue: capability rules with
  argument patterns, risk tiers, default-deny and approval escalation
- Check / VerificationLoop: weighted verification with revision feedback
- Span / Trace / Tracer: span trees, dominant path, percentiles, error rates
- Checkpoint / StateStore: hashed checkpoints, restore, rollback and diff
- Interrupt / HumanInterface: questions the loop must stop for
- EvalCase / EvalSuite / pass_at_k: evaluation harness with tag breakdowns
- HARNESS_PRIMITIVES / HarnessBlueprint: audit an agent build against the
  fourteen harness concerns and get graded recommendations
- AgentLoop: a bounded reason/act loop with loop detection, denial handling,
  approval escalation and token exhaustion
- HarnessEngine + engine: one facade over all of the above

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

TOKEN_PATTERN = re.compile(r"[A-Za-z]+|[0-9]+|[^\sA-Za-z0-9]")
WORD_PATTERN = re.compile(r"[a-z0-9]+")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


# ── Token accounting ──────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate: short pieces count 1, long split by 4."""
    if not text:
        return 0
    total = 0
    for piece in TOKEN_PATTERN.findall(text):
        total += 1 if len(piece) <= 4 else math.ceil(len(piece) / 4)
    return total


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Cut text on a word boundary so the estimate stays under max_tokens."""
    if max_tokens <= 0 or not text:
        return ""
    pieces = text.split()
    kept: list[str] = []
    for piece in pieces:
        candidate = " ".join(kept + [piece])
        if estimate_tokens(candidate) > max_tokens:
            break
        kept.append(piece)
    return " ".join(kept)


@dataclass
class Message:
    """One turn in a model context window."""

    role: str
    content: str
    pinned: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content) + estimate_tokens(self.role) + 2

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content,
                "pinned": self.pinned, "tokens": self.tokens}


@dataclass
class ContextBudget:
    """A model window split into prompt room, output reserve and system prompt."""

    window: int = 8192
    reserve_output: int = 1024
    system_tokens: int = 0

    def __post_init__(self) -> None:
        if self.window <= 0:
            raise ValueError("window must be positive")
        if self.reserve_output < 0:
            raise ValueError("reserve_output must be >= 0")

    def available(self) -> int:
        return max(0, self.window - self.reserve_output - self.system_tokens)

    def used(self, messages: Iterable[Message]) -> int:
        return sum(message.tokens for message in messages)

    def fits(self, messages: Iterable[Message]) -> bool:
        return self.used(messages) <= self.available()

    def usage(self, messages: Iterable[Message]) -> float:
        available = self.available()
        if available <= 0:
            return 1.0
        return round(min(1.0, self.used(messages) / available), 4)

    def headroom(self, messages: Iterable[Message]) -> int:
        return max(0, self.available() - self.used(messages))


# ── Context compaction ────────────────────────────────────────────────────

@dataclass
class CompactionResult:
    """Outcome of fitting a conversation into a context budget."""

    messages: list[Message]
    strategy: str
    tokens_before: int
    tokens_after: int
    dropped: int
    summarised: int
    summary: str = ""
    fits: bool = True

    @property
    def saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def ratio(self) -> float:
        if self.tokens_before == 0:
            return 0.0
        return round(self.tokens_after / self.tokens_before, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "saved": self.saved,
            "ratio": self.ratio,
            "dropped": self.dropped,
            "summarised": self.summarised,
            "fits": self.fits,
        }


def split_sentences(text: str) -> list[str]:
    return [chunk.strip() for chunk in SENTENCE_SPLIT.split(text or "") if chunk.strip()]


class ContextCompactor:
    """Fits a message list into a budget without silently losing everything."""

    STRATEGIES = ("truncate", "sliding", "summarise", "hierarchical")

    def __init__(self, budget: ContextBudget, strategy: str = "summarise",
                 keep_recent: int = 4, summary_tokens: int = 160,
                 tier_size: int = 4) -> None:
        if strategy not in self.STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}")
        self.budget = budget
        self.strategy = strategy
        self.keep_recent = max(1, keep_recent)
        self.summary_tokens = max(16, summary_tokens)
        self.tier_size = max(1, tier_size)

    # -- summarisation ----------------------------------------------------
    def summarise(self, messages: Iterable[Message], query: str = "",
                  max_tokens: int = 160) -> str:
        """Extractive summary: score sentences by query overlap and recency."""
        terms = set(WORD_PATTERN.findall((query or "").lower()))
        scored: list[tuple[float, int, str]] = []
        for index, message in enumerate(messages):
            for sentence in split_sentences(message.content):
                words = set(WORD_PATTERN.findall(sentence.lower()))
                overlap = len(words & terms)
                density = overlap / math.sqrt(len(words) + 1)
                recency = 1.0 / (1.0 + index)
                length_bonus = min(len(sentence), 200) / 1000.0
                score = round(2.0 * density + recency + length_bonus, 6)
                scored.append((score, index, f"{message.role}: {sentence}"))
        if not scored:
            return ""
        # deterministic: score desc, original order asc
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen: list[str] = []
        for _, _, sentence in scored:
            candidate = " | ".join(chosen + [sentence])
            if estimate_tokens(candidate) > max_tokens:
                if not chosen:
                    chosen.append(truncate_to_tokens(sentence, max_tokens))
                break
            chosen.append(sentence)
        return " | ".join(chosen).strip()

    def _hierarchical_summary(self, messages: list[Message], query: str = "") -> str:
        if not messages:
            return ""
        chunks = [messages[i:i + self.tier_size]
                  for i in range(0, len(messages), self.tier_size)]
        per_chunk = max(24, self.summary_tokens // max(1, len(chunks)))
        parts = [self.summarise(chunk, query, per_chunk) for chunk in chunks]
        text = " | ".join(part for part in parts if part)
        depth = 0
        while text and estimate_tokens(text) > self.summary_tokens and depth < 4:
            text = self.summarise([Message("summary", text)], query,
                                  max(24, self.summary_tokens // 2))
            depth += 1
        return text

    # -- compaction -------------------------------------------------------
    def _fit_tail(self, pinned: list[Message], tail: list[Message],
                  available: int) -> tuple[list[Message], int]:
        kept = list(tail)
        dropped = 0
        base = sum(message.tokens for message in pinned)
        while kept and base + sum(message.tokens for message in kept) > available:
            kept.pop(0)
            dropped += 1
        return kept, dropped

    def compact(self, messages: Iterable[Message], query: str = "") -> CompactionResult:
        messages = list(messages)
        before = sum(message.tokens for message in messages)
        available = max(1, self.budget.available())
        if before <= available:
            return CompactionResult(messages, self.strategy, before, before, 0, 0)

        pinned = [message for message in messages if message.pinned]
        rest = [message for message in messages if not message.pinned]
        summaries: list[Message] = []
        dropped = 0
        kept: list[Message]

        if self.strategy == "truncate":
            kept, dropped = self._fit_tail(pinned, rest, available)
        elif self.strategy == "sliding":
            window = rest[-self.keep_recent:]
            dropped = len(rest) - len(window)
            kept, extra = self._fit_tail(pinned, window, available)
            dropped += extra
        else:
            head = rest[:-self.keep_recent] if len(rest) > self.keep_recent else []
            tail = rest[-self.keep_recent:] if head else list(rest)
            if self.strategy == "hierarchical":
                text = self._hierarchical_summary(head, query)
            else:
                text = self.summarise(head, query, self.summary_tokens)
            summary_tokens = sum(message.tokens for message in pinned + tail)
            room = max(16, available - summary_tokens - 8)
            if text:
                text = truncate_to_tokens(text, room)
                summaries.append(Message("summary", text, pinned=True))
            dropped = len(head)
            kept, extra = self._fit_tail(pinned + summaries, tail, available)
            dropped += extra

        result_messages = pinned + summaries + kept
        after = sum(message.tokens for message in result_messages)
        return CompactionResult(
            messages=result_messages,
            strategy=self.strategy,
            tokens_before=before,
            tokens_after=after,
            dropped=dropped,
            summarised=len(summaries),
            summary=summaries[0].content if summaries else "",
            fits=after <= available,
        )

    def compact_until_fits(self, messages: Iterable[Message], query: str = "",
                           max_rounds: int = 4) -> CompactionResult:
        """Compact, and if still over budget, fall back through harder strategies."""
        order = ["summarise", "hierarchical", "sliding", "truncate"]
        start = order.index(self.strategy) if self.strategy in order else 0
        result = self.compact(messages, query)
        rounds = 0
        while not result.fits and rounds < max_rounds:
            rounds += 1
            start = min(len(order) - 1, start + 1)
            self.strategy = order[start]
            self.keep_recent = max(1, self.keep_recent - 1)
            result = self.compact(result.messages, query)
        return result


# ── Planning ──────────────────────────────────────────────────────────────

@dataclass
class Subtask:
    """One node in a task decomposition graph."""

    task_id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    est_tokens: int = 200
    risk: str = "low"

    def __post_init__(self) -> None:
        if self.est_tokens <= 0:
            raise ValueError("est_tokens must be positive")
        if self.risk not in RISK_ORDER:
            raise ValueError(f"unknown risk {self.risk!r}")

    def as_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "title": self.title,
                "depends_on": list(self.depends_on),
                "est_tokens": self.est_tokens, "risk": self.risk}


@dataclass
class Plan:
    """A validated dependency graph of subtasks."""

    goal: str
    subtasks: list[Subtask]

    def __post_init__(self) -> None:
        self.index: dict[str, Subtask] = {}
        for task in self.subtasks:
            if task.task_id in self.index:
                raise ValueError(f"duplicate task id {task.task_id!r}")
            self.index[task.task_id] = task
        for task in self.subtasks:
            for dep in task.depends_on:
                if dep not in self.index:
                    raise ValueError(f"{task.task_id!r} depends on unknown {dep!r}")
        self.topological_order()  # raises on cycles at construction time

    # -- graph algorithms -------------------------------------------------
    def topological_order(self) -> list[str]:
        indegree = {task.task_id: len(set(task.depends_on)) for task in self.subtasks}
        children: dict[str, list[str]] = {task.task_id: [] for task in self.subtasks}
        for task in self.subtasks:
            for dep in set(task.depends_on):
                children[dep].append(task.task_id)
        ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        order: list[str] = []
        while ready:
            task_id = ready.pop(0)
            order.append(task_id)
            for child in sorted(children[task_id]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
            ready.sort()
        if len(order) != len(self.subtasks):
            raise ValueError("plan contains a dependency cycle")
        return order

    def batches(self) -> list[list[str]]:
        levels: dict[str, int] = {}
        for task_id in self.topological_order():
            task = self.index[task_id]
            levels[task_id] = 1 + max((levels[dep] for dep in task.depends_on), default=-1)
        grouped: dict[int, list[str]] = {}
        for task_id, level in levels.items():
            grouped.setdefault(level, []).append(task_id)
        return [sorted(grouped[level]) for level in sorted(grouped)]

    def critical_path(self) -> list[str]:
        finish: dict[str, int] = {}
        parent: dict[str, str | None] = {}
        for task_id in self.topological_order():
            task = self.index[task_id]
            if not task.depends_on:
                finish[task_id] = task.est_tokens
                parent[task_id] = None
            else:
                best_parent = max(task.depends_on, key=lambda dep: (finish[dep], dep))
                finish[task_id] = finish[best_parent] + task.est_tokens
                parent[task_id] = best_parent
        end: str | None = max(finish, key=lambda task_id: (finish[task_id], task_id))
        path: list[str] = []
        while end is not None:
            path.append(end)
            end = parent[end]
        return list(reversed(path))

    def path_weight(self, path: Iterable[str] | None = None) -> int:
        ids = list(path) if path is not None else self.critical_path()
        return sum(self.index[task_id].est_tokens for task_id in ids)

    def total_tokens(self) -> int:
        return sum(task.est_tokens for task in self.subtasks)

    def risk_ranking(self) -> list[str]:
        return [task.task_id for task in sorted(
            self.subtasks, key=lambda task: (-RISK_ORDER[task.risk], task.task_id))]

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "subtasks": [task.as_dict() for task in self.subtasks],
            "order": self.topological_order(),
            "batches": self.batches(),
            "critical_path": self.critical_path(),
            "total_tokens": self.total_tokens(),
        }


class TaskDecomposer:
    """Turns a goal into a typed, dependency-aware plan."""

    def decompose(self, goal: str, steps: Iterable[str | Subtask | dict[str, Any]]) -> Plan:
        subtasks: list[Subtask] = []
        previous: str | None = None
        for position, raw in enumerate(steps, start=1):
            if isinstance(raw, Subtask):
                subtasks.append(raw)
                previous = raw.task_id
                continue
            if isinstance(raw, dict):
                task_id = str(raw.get("task_id") or f"s{position}")
                subtasks.append(Subtask(
                    task_id=task_id,
                    title=str(raw.get("title") or task_id),
                    depends_on=list(raw.get("depends_on") or []),
                    est_tokens=int(raw.get("est_tokens", 200)),
                    risk=str(raw.get("risk", "low")),
                ))
                previous = task_id
                continue
            task_id = f"s{position}"
            subtasks.append(Subtask(
                task_id=task_id, title=str(raw),
                depends_on=[previous] if previous else [],
            ))
            previous = task_id
        if not subtasks:
            raise ValueError("a plan needs at least one step")
        return Plan(goal=goal, subtasks=subtasks)

    def split_by_budget(self, plan: Plan, batch_tokens: int) -> list[list[str]]:
        """Pack topologically ordered tasks into token-bounded execution groups."""
        if batch_tokens <= 0:
            raise ValueError("batch_tokens must be positive")
        groups: list[list[str]] = []
        current: list[str] = []
        used = 0
        for task_id in plan.topological_order():
            cost = plan.index[task_id].est_tokens
            if current and used + cost > batch_tokens:
                groups.append(current)
                current = []
                used = 0
            current.append(task_id)
            used += cost
        if current:
            groups.append(current)
        return groups


# ── Tools ─────────────────────────────────────────────────────────────────

TYPES = ("string", "integer", "number", "boolean")


@dataclass(frozen=True)
class ParamSpec:
    """One typed parameter of a tool schema."""

    name: str
    type: str = "string"
    required: bool = True
    enum: tuple[str, ...] = ()
    default: Any = None

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"unsupported parameter type {self.type!r}")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "required": self.required}
        if self.enum:
            payload["enum"] = list(self.enum)
        if self.default is not None:
            payload["default"] = self.default
        return payload


@dataclass
class ToolSpec:
    """A declarative tool contract the loop can validate against."""

    name: str
    description: str
    parameters: list[ParamSpec] = field(default_factory=list)
    risk: str = "low"
    cost: int = 8

    def __post_init__(self) -> None:
        if self.risk not in RISK_ORDER:
            raise ValueError(f"unknown risk {self.risk!r}")

    def required(self) -> list[str]:
        return [param.name for param in self.parameters if param.required]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "parameters": {param.name: param.as_dict() for param in self.parameters},
        }


@dataclass
class ArgProblem:
    field: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[ArgProblem] = field(default_factory=list)
    cleaned: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": [error.as_dict() for error in self.errors],
                "cleaned": self.cleaned}


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any] | None) -> ValidationResult:
    """Validate and coerce arguments against a ToolSpec."""
    arguments = dict(arguments or {})
    errors: list[ArgProblem] = []
    cleaned: dict[str, Any] = {}
    known = {param.name: param for param in spec.parameters}

    for name in arguments:
        if name not in known:
            errors.append(ArgProblem(name, "unknown parameter"))

    for name, param in known.items():
        if name not in arguments:
            if param.required:
                errors.append(ArgProblem(name, "missing required parameter"))
            elif param.default is not None:
                cleaned[name] = param.default
            continue
        value = arguments[name]
        try:
            if param.type == "integer":
                if isinstance(value, bool):
                    raise ValueError("expected integer")
                cleaned[name] = int(value)
            elif param.type == "number":
                if isinstance(value, bool):
                    raise ValueError("expected number")
                cleaned[name] = float(value)
            elif param.type == "boolean":
                if isinstance(value, bool):
                    cleaned[name] = value
                elif isinstance(value, str) and value.lower() in ("true", "false"):
                    cleaned[name] = value.lower() == "true"
                else:
                    raise ValueError("expected boolean")
            else:
                if isinstance(value, (dict, list)):
                    raise ValueError("expected string")
                cleaned[name] = str(value)
        except (TypeError, ValueError) as exc:
            errors.append(ArgProblem(name, str(exc)))
            continue
        if param.enum and cleaned[name] not in param.enum:
            errors.append(ArgProblem(
                name, f"must be one of {', '.join(param.enum)}"))
    return ValidationResult(ok=not errors, errors=errors, cleaned=cleaned)


@dataclass
class ToolCallResult:
    ok: bool
    tool: str
    value: Any = None
    error: str = ""
    cost: int = 0

    def observation(self) -> str:
        if self.ok:
            return str(self.value)
        return f"error: {self.error}"

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "tool": self.tool, "value": self.value,
                "error": self.error, "cost": self.cost}


class ToolRegistry:
    """Holds tool contracts and their real handlers."""

    def __init__(self, tools: Iterable[tuple[ToolSpec, Callable[..., Any]]] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        for spec, handler in tools:
            self.register(spec, handler)

    def register(self, spec: ToolSpec, handler: Callable[..., Any]) -> None:
        if spec.name in self._specs:
            raise ValueError(f"tool {spec.name!r} already registered")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def risk_of(self, name: str) -> str:
        spec = self._specs.get(name)
        return spec.risk if spec else "high"

    def validate(self, name: str, arguments: dict[str, Any] | None) -> ValidationResult:
        spec = self._specs.get(name)
        if spec is None:
            return ValidationResult(ok=False, errors=[ArgProblem("tool", "unknown tool")])
        return validate_arguments(spec, arguments)

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        spec = self._specs.get(name)
        if spec is None:
            return ToolCallResult(ok=False, tool=name, error=f"unknown tool {name!r}")
        validation = validate_arguments(spec, arguments)
        if not validation.ok:
            detail = "; ".join(f"{e.field}: {e.message}" for e in validation.errors)
            return ToolCallResult(ok=False, tool=name, error=detail, cost=0)
        try:
            value = self._handlers[name](**validation.cleaned)
        except Exception as exc:  # handler failures are observations, not crashes
            return ToolCallResult(ok=False, tool=name, error=f"{type(exc).__name__}: {exc}",
                                  cost=spec.cost)
        return ToolCallResult(ok=True, tool=name, value=value, cost=spec.cost)

    def describe(self) -> str:
        lines = []
        for name in self.names():
            spec = self._specs[name]
            required = ", ".join(spec.required()) or "no required args"
            lines.append(f"- {name}({required}) [{spec.risk}] — {spec.description}")
        return "\n".join(lines)


def default_registry(files: dict[str, str] | None = None) -> ToolRegistry:
    """A small but genuinely functional workspace toolkit for the harness."""
    store: dict[str, str] = dict(files or {})

    def read_file(path: str) -> str:
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def write_file(path: str, content: str) -> str:
        existed = path in store
        store[path] = content
        action = "updated" if existed else "created"
        return f"{action} {path} ({len(content)} chars)"

    def grep(pattern: str, path: str = "") -> str:
        regex = re.compile(pattern)
        hits: list[str] = []
        for name in sorted(store):
            if path and name != path:
                continue
            for number, line in enumerate(store[name].splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{name}:{number}: {line.strip()}")
        return "\n".join(hits) if hits else "no matches"

    def count_tokens(text: str) -> int:
        return estimate_tokens(text)

    def check_syntax(source: str) -> str:
        try:
            compile(source, "<harness>", "exec")
        except SyntaxError as exc:
            return f"syntax error at line {exc.lineno}: {exc.msg}"
        return "ok"

    registry = ToolRegistry()
    registry.register(ToolSpec(
        "read_file", "Read a file from the harness workspace.",
        [ParamSpec("path")], risk="low"), read_file)
    registry.register(ToolSpec(
        "write_file", "Create or replace a file in the harness workspace.",
        [ParamSpec("path"), ParamSpec("content")], risk="medium"), write_file)
    registry.register(ToolSpec(
        "grep", "Search workspace files for a regular expression.",
        [ParamSpec("pattern"), ParamSpec("path", required=False, default="")],
        risk="low"), grep)
    registry.register(ToolSpec(
        "count_tokens", "Count estimated tokens for a string.",
        [ParamSpec("text")], risk="low"), count_tokens)
    registry.register(ToolSpec(
        "check_syntax", "Compile Python source and report syntax errors.",
        [ParamSpec("source")], risk="low"), check_syntax)
    registry.workspace = store  # type: ignore[attr-defined]
    return registry


# ── Permissions ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PermissionRule:
    """A capability rule: tool glob, optional argument pattern, risk tier, verdict."""

    capability: str
    decision: str = "allow"          # allow | ask | deny
    argument: str = ""
    pattern: str = ""
    risk_tier: str = "any"           # any | low | medium | high | critical
    priority: int = 0

    def __post_init__(self) -> None:
        if self.decision not in ("allow", "ask", "deny"):
            raise ValueError(f"unknown decision {self.decision!r}")
        if self.risk_tier != "any" and self.risk_tier not in RISK_ORDER:
            raise ValueError(f"unknown risk tier {self.risk_tier!r}")

    def specificity(self) -> tuple[int, int, int]:
        return (1 if (self.argument and self.pattern) else 0,
                self.priority,
                len(self.capability.replace("*", "")))


@dataclass
class PermissionDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    rule: str = ""
    risk: str = "low"

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "requires_approval": self.requires_approval,
                "reason": self.reason, "rule": self.rule, "risk": self.risk}


def _glob(pattern: str, value: str) -> bool:
    """Tiny glob matcher supporting * and ? without importing fnmatch semantics."""
    regex = "^" + "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char)
        for char in pattern
    ) + "$"
    return re.match(regex, value) is not None


DEFAULT_RULES = [
    PermissionRule("read_*", "allow", priority=5),
    PermissionRule("grep", "allow", priority=5),
    PermissionRule("count_tokens", "allow", priority=5),
    PermissionRule("check_syntax", "allow", priority=5),
    PermissionRule("write_file", "ask", risk_tier="medium", priority=10),
    PermissionRule("run_command", "ask", argument="command",
                   pattern="pytest*", priority=20),
    PermissionRule("run_command", "deny", priority=1),
    PermissionRule("delete_*", "deny", priority=30),
    PermissionRule("deploy_*", "ask", risk_tier="high", priority=30),
]


class PermissionGate:
    """Default-deny capability gate with argument inspection."""

    def __init__(self, rules: Iterable[PermissionRule] | None = None,
                 registry: ToolRegistry | None = None) -> None:
        self.rules = list(DEFAULT_RULES if rules is None else rules)
        self.registry = registry
        self.audit: list[PermissionDecision] = []

    def _matching(self, tool: str, arguments: dict[str, Any], risk: str) -> list[PermissionRule]:
        matches = []
        for rule in self.rules:
            if not _glob(rule.capability, tool):
                continue
            if rule.risk_tier != "any" and rule.risk_tier != risk:
                continue
            if rule.argument:
                value = str(arguments.get(rule.argument, ""))
                if rule.pattern and not _glob(rule.pattern, value):
                    continue
            matches.append(rule)
        return matches

    def decide(self, tool: str, arguments: dict[str, Any] | None = None) -> PermissionDecision:
        arguments = dict(arguments or {})
        risk = self.registry.risk_of(tool) if self.registry else "low"
        matches = self._matching(tool, arguments, risk)
        if not matches:
            decision = PermissionDecision(
                allowed=False, requires_approval=False,
                reason=f"no rule permits {tool!r}", risk=risk)
        else:
            rule = max(matches, key=lambda item: item.specificity())
            decision = PermissionDecision(
                allowed=rule.decision == "allow",
                requires_approval=rule.decision == "ask",
                reason=("allowed by " + rule.capability if rule.decision == "allow"
                        else f"requires approval via {rule.capability}"
                        if rule.decision == "ask" else f"denied by {rule.capability}"),
                rule=rule.capability,
                risk=risk,
            )
        self.audit.append(decision)
        return decision

    def allowed_tools(self, registry: ToolRegistry | None = None) -> list[str]:
        registry = registry or self.registry
        if registry is None:
            return []
        return [name for name in registry.names()
                if self.decide(name, {}).allowed]

    def report(self) -> dict[str, Any]:
        return {
            "checks": len(self.audit),
            "allowed": sum(1 for d in self.audit if d.allowed),
            "approval": sum(1 for d in self.audit if d.requires_approval),
            "denied": sum(1 for d in self.audit if not d.allowed and not d.requires_approval),
            "rules": len(self.rules),
        }


@dataclass
class ApprovalRequest:
    request_id: str
    tool: str
    arguments: dict[str, Any]
    risk: str
    reason: str
    created_at: float = field(default_factory=time.time)
    approved: bool | None = None
    approver: str = ""

    @property
    def resolved(self) -> bool:
        return self.approved is not None

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "tool": self.tool,
                "arguments": self.arguments, "risk": self.risk,
                "reason": self.reason, "resolved": self.resolved,
                "approved": self.approved, "approver": self.approver}


class HumanApprovalQueue:
    """Escalation queue for decisions the gate refuses to make alone."""

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    def submit(self, tool: str, arguments: dict[str, Any], risk: str,
               reason: str) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=f"appr-{len(self.requests) + 1:03d}",
            tool=tool, arguments=dict(arguments), risk=risk, reason=reason)
        self.requests.append(request)
        return request

    def pending(self, risk: str | None = None) -> list[ApprovalRequest]:
        return [request for request in self.requests
                if not request.resolved and (risk is None or request.risk == risk)]

    def resolve(self, request_id: str, approved: bool, approver: str = "operator") -> ApprovalRequest:
        for request in self.requests:
            if request.request_id == request_id:
                request.approved = approved
                request.approver = approver
                return request
        raise KeyError(request_id)

    def stats(self) -> dict[str, Any]:
        resolved = [request for request in self.requests if request.resolved]
        return {
            "total": len(self.requests),
            "pending": len(self.requests) - len(resolved),
            "approved": sum(1 for request in resolved if request.approved),
            "denied": sum(1 for request in resolved if request.approved is False),
            "by_risk": {risk: sum(1 for r in self.requests if r.risk == risk)
                        for risk in RISK_ORDER},
        }


# ── Verification ──────────────────────────────────────────────────────────

@dataclass
class Check:
    """A named verification check over an artifact."""

    name: str
    fn: Callable[[str], tuple[bool, str]]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("weight must be positive")

    def run(self, artifact: str) -> "CheckResult":
        try:
            passed, detail = self.fn(artifact)
        except Exception as exc:  # a crashing check is a failing check
            return CheckResult(self.name, False, f"{type(exc).__name__}: {exc}",
                               weight=self.weight)
        return CheckResult(self.name, bool(passed), str(detail), weight=self.weight)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    weight: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed,
                "detail": self.detail, "weight": self.weight}


@dataclass
class VerificationAttempt:
    attempt: int
    artifact: str
    checks: list[CheckResult]
    score: float
    passed: bool

    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.passed]

    def as_dict(self) -> dict[str, Any]:
        return {"attempt": self.attempt, "score": self.score, "passed": self.passed,
                "checks": [check.as_dict() for check in self.checks]}


@dataclass
class VerificationReport:
    attempts: list[VerificationAttempt]
    passed: bool
    final_artifact: str

    @property
    def attempts_used(self) -> int:
        return len(self.attempts)

    @property
    def feedback(self) -> list[str]:
        if not self.attempts:
            return []
        return [f"{check.name}: {check.detail}"
                for check in self.attempts[-1].failures()]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "attempts_used": self.attempts_used,
            "final_score": round(self.attempts[-1].score, 4) if self.attempts else 0.0,
            "feedback": self.feedback,
            "history": [attempt.as_dict() for attempt in self.attempts],
        }


class VerificationLoop:
    """Runs weighted checks, feeds failures back, and retries with revisions."""

    def __init__(self, checks: Iterable[Check], max_attempts: int = 3,
                 threshold: float = 1.0) -> None:
        self.checks = list(checks)
        if not self.checks:
            raise ValueError("verification needs at least one check")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.threshold = threshold

    def evaluate(self, artifact: str, attempt: int = 1) -> VerificationAttempt:
        results = [check.run(artifact) for check in self.checks]
        total_weight = sum(result.weight for result in results)
        earned = sum(result.weight for result in results if result.passed)
        score = round(earned / total_weight, 4) if total_weight else 0.0
        return VerificationAttempt(
            attempt=attempt, artifact=artifact, checks=results,
            score=score, passed=score >= self.threshold)

    def run(self, artifact: str,
            revise: Callable[[str, list[str]], str] | None = None
            ) -> VerificationReport:
        attempts: list[VerificationAttempt] = []
        current = artifact
        for attempt in range(1, self.max_attempts + 1):
            result = self.evaluate(current, attempt)
            attempts.append(result)
            if result.passed or revise is None or attempt == self.max_attempts:
                return VerificationReport(attempts=attempts, passed=result.passed,
                                          final_artifact=current)
            feedback = [f"{check.name}: {check.detail}" for check in result.failures()]
            current = revise(current, feedback)
        return VerificationReport(attempts=attempts, passed=False, final_artifact=current)


# ── Observability ─────────────────────────────────────────────────────────

@dataclass
class Span:
    span_id: str
    name: str
    parent_id: str | None = None
    start: float = 0.0
    end: float | None = None
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.end is None:
            return 0.0
        return round(max(0.0, self.end - self.start), 6)

    def close(self, end: float | None = None, status: str = "ok") -> "Span":
        self.end = time.monotonic() if end is None else end
        self.status = status
        return self

    def as_dict(self) -> dict[str, Any]:
        return {"span_id": self.span_id, "name": self.name, "parent_id": self.parent_id,
                "start": self.start, "end": self.end, "duration": self.duration,
                "status": self.status, "attributes": dict(self.attributes)}


def percentile(values: Iterable[float], q: float) -> float:
    """Linear-interpolated percentile; q in [0, 1]."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * max(0.0, min(1.0, q))
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return round(ordered[low], 6)
    blended = ordered[low] + (ordered[high] - ordered[low]) * (position - low)
    return round(blended, 6)


@dataclass
class Trace:
    """A tree of spans with real timing analysis."""

    trace_id: str
    spans: list[Span] = field(default_factory=list)

    def add(self, name: str, parent_id: str | None = None,
            start: float | None = None, **attributes: Any) -> Span:
        span = Span(
            span_id=f"span-{len(self.spans) + 1:03d}",
            name=name, parent_id=parent_id,
            start=time.monotonic() if start is None else start,
            attributes=dict(attributes))
        self.spans.append(span)
        return span

    def get(self, span_id: str) -> Span | None:
        for span in self.spans:
            if span.span_id == span_id:
                return span
        return None

    def roots(self) -> list[Span]:
        return [span for span in self.spans if span.parent_id is None]

    def children(self, span_id: str) -> list[Span]:
        return [span for span in self.spans if span.parent_id == span_id]

    def depth(self, span_id: str) -> int:
        depth = 0
        current = self.get(span_id)
        while current is not None and current.parent_id is not None:
            depth += 1
            current = self.get(current.parent_id)
        return depth

    def dominant_path(self) -> list[str]:
        """Root-to-leaf chain that consumes the most wall-clock time."""
        roots = [span for span in self.roots() if span.end is not None]
        if not roots:
            return []
        current = max(roots, key=lambda span: (span.duration, span.span_id))
        path = [current.span_id]
        while True:
            children = [child for child in self.children(current.span_id)
                        if child.end is not None]
            if not children:
                break
            current = max(children, key=lambda span: (span.duration, span.span_id))
            path.append(current.span_id)
        return path

    def total_duration(self) -> float:
        closed = [span for span in self.spans if span.end is not None]
        if not closed:
            return 0.0
        start = min(span.start for span in closed)
        end = max(span.end or span.start for span in closed)
        return round(end - start, 6)

    def error_spans(self) -> list[Span]:
        return [span for span in self.spans if span.status != "ok"]

    def summary(self) -> dict[str, Any]:
        durations = [span.duration for span in self.spans if span.end is not None]
        by_name: dict[str, dict[str, Any]] = {}
        for span in self.spans:
            bucket = by_name.setdefault(span.name, {"count": 0, "duration": 0.0})
            bucket["count"] += 1
            bucket["duration"] = round(bucket["duration"] + span.duration, 6)
        slowest = max((span for span in self.spans if span.end is not None),
                      key=lambda span: (span.duration, span.span_id), default=None)
        return {
            "trace_id": self.trace_id,
            "spans": len(self.spans),
            "duration": self.total_duration(),
            "errors": len(self.error_spans()),
            "error_rate": round(len(self.error_spans()) / len(self.spans), 4)
            if self.spans else 0.0,
            "p50": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
            "slowest": slowest.name if slowest else "",
            "max_depth": max((self.depth(span.span_id) for span in self.spans), default=0),
            "by_name": by_name,
            "dominant_path": self.dominant_path(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id,
                "spans": [span.as_dict() for span in self.spans]}


class Tracer:
    """Convenience tracer that nests spans opened inside context managers."""

    def __init__(self, trace: Trace | None = None) -> None:
        self.trace = trace or Trace(trace_id=f"trace-{uuid.uuid4().hex[:8]}")
        self._stack: list[str] = []

    @property
    def current(self) -> str | None:
        return self._stack[-1] if self._stack else None

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        span = self.trace.add(name, parent_id=self.current, **attributes)
        self._stack.append(span.span_id)
        try:
            yield span
        except Exception as exc:
            span.close(status="error")
            span.attributes["error"] = f"{type(exc).__name__}: {exc}"
            raise
        else:
            span.close()
        finally:
            if self._stack and self._stack[-1] == span.span_id:
                self._stack.pop()


# ── State ─────────────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    checkpoint_id: str
    step: int
    payload: dict[str, Any]
    digest: str
    created_at: float = field(default_factory=time.time)

    def verify(self) -> bool:
        return self.digest == _digest(self.payload)

    def as_dict(self) -> dict[str, Any]:
        return {"checkpoint_id": self.checkpoint_id, "step": self.step,
                "digest": self.digest, "verified": self.verify(),
                "created_at": self.created_at}


def _digest(payload: dict[str, Any]) -> str:
    serialised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def diff_states(left: dict[str, Any], right: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(right) - set(left)),
        "removed": sorted(set(left) - set(right)),
        "changed": sorted(key for key in set(left) & set(right)
                          if left[key] != right[key]),
    }


class StateStore:
    """Checkpointed task state: save, restore, rollback and diff."""

    def __init__(self) -> None:
        self.checkpoints: list[Checkpoint] = []

    def save(self, step: int, state: dict[str, Any]) -> Checkpoint:
        payload = json.loads(json.dumps(state, sort_keys=True, default=str))
        digest = _digest(payload)
        checkpoint = Checkpoint(
            checkpoint_id=f"ckpt-{len(self.checkpoints) + 1:03d}-{digest[:8]}",
            step=step, payload=payload, digest=digest)
        self.checkpoints.append(checkpoint)
        return checkpoint

    def latest(self) -> Checkpoint | None:
        return self.checkpoints[-1] if self.checkpoints else None

    def get(self, checkpoint_id: str) -> Checkpoint:
        for checkpoint in self.checkpoints:
            if checkpoint.checkpoint_id == checkpoint_id:
                return checkpoint
        raise KeyError(checkpoint_id)

    def restore(self, checkpoint_id: str | None = None) -> dict[str, Any]:
        checkpoint = self.latest() if checkpoint_id is None else self.get(checkpoint_id)
        if checkpoint is None:
            raise LookupError("no checkpoints stored")
        if not checkpoint.verify():
            raise ValueError("checkpoint digest mismatch")
        return json.loads(json.dumps(checkpoint.payload))

    def rollback(self, steps: int = 1) -> dict[str, Any]:
        if steps < 1:
            raise ValueError("steps must be >= 1")
        if len(self.checkpoints) <= steps:
            raise LookupError("not enough checkpoints to roll back")
        return self.restore(self.checkpoints[-1 - steps].checkpoint_id)

    def diff(self, left: str, right: str) -> dict[str, list[str]]:
        return diff_states(self.get(left).payload, self.get(right).payload)

    def history(self) -> list[dict[str, Any]]:
        return [checkpoint.as_dict() for checkpoint in self.checkpoints]

    def __len__(self) -> int:
        return len(self.checkpoints)


# ── Human in the loop ─────────────────────────────────────────────────────

@dataclass
class Interrupt:
    interrupt_id: str
    question: str
    options: list[str] = field(default_factory=list)
    risk: str = "medium"
    answer: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def resolved(self) -> bool:
        return self.answer is not None

    def as_dict(self) -> dict[str, Any]:
        return {"interrupt_id": self.interrupt_id, "question": self.question,
                "options": list(self.options), "risk": self.risk,
                "answer": self.answer, "resolved": self.resolved}


class HumanInterface:
    """Collects questions the loop must stop for and their answers."""

    def __init__(self, auto_approve_risk: str = "low") -> None:
        self.interrupts: list[Interrupt] = []
        self.auto_approve_risk = auto_approve_risk

    def ask(self, question: str, options: Iterable[str] = (),
            risk: str = "medium") -> Interrupt:
        if risk not in RISK_ORDER:
            raise ValueError(f"unknown risk {risk!r}")
        interrupt = Interrupt(
            interrupt_id=f"int-{len(self.interrupts) + 1:03d}",
            question=question, options=list(options), risk=risk)
        if RISK_ORDER[risk] <= RISK_ORDER[self.auto_approve_risk]:
            interrupt.answer = "auto-approved"
        self.interrupts.append(interrupt)
        return interrupt

    def answer(self, interrupt_id: str, answer: str) -> Interrupt:
        for interrupt in self.interrupts:
            if interrupt.interrupt_id == interrupt_id:
                if answer not in interrupt.options and interrupt.options:
                    raise ValueError(f"{answer!r} is not one of the offered options")
                interrupt.answer = answer
                return interrupt
        raise KeyError(interrupt_id)

    def pending(self) -> list[Interrupt]:
        return [interrupt for interrupt in self.interrupts if not interrupt.resolved]

    def escalate(self, risk: str) -> bool:
        return RISK_ORDER[risk] > RISK_ORDER[self.auto_approve_risk]

    def stats(self) -> dict[str, Any]:
        return {
            "asks": len(self.interrupts),
            "pending": len(self.pending()),
            "answered": sum(1 for i in self.interrupts if i.resolved),
        }


# ── Evaluation ────────────────────────────────────────────────────────────

def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator: 1 - C(n-c, k) / C(n, k)."""
    if n <= 0 or k <= 0:
        return 0.0
    k = min(k, n)
    c = max(0, min(c, n))
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return round(1.0 - math.comb(n - c, k) / math.comb(n, k), 6)


def token_overlap(expected: str, actual: str) -> float:
    expected_terms = set(WORD_PATTERN.findall((expected or "").lower()))
    if not expected_terms:
        return 1.0 if not (actual or "").strip() else 0.0
    actual_terms = set(WORD_PATTERN.findall((actual or "").lower()))
    return round(len(expected_terms & actual_terms) / len(expected_terms), 4)


@dataclass
class EvalCase:
    case_id: str
    prompt: str
    expected: str
    weight: float = 1.0
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("weight must be positive")


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    score: float
    output: str
    detail: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "passed": self.passed, "score": self.score,
                "output": self.output, "detail": self.detail, "tags": list(self.tags)}


@dataclass
class EvalReport:
    results: list[CaseResult]
    threshold: float = 0.8
    weights: dict[str, float] = field(default_factory=dict)

    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return round(sum(1 for result in self.results if result.passed) / len(self.results), 4)

    def weighted_score(self) -> float:
        total = sum(self.weights.get(result.case_id, 1.0) for result in self.results)
        if total == 0:
            return 0.0
        earned = sum(self.weights.get(result.case_id, 1.0) * result.score
                     for result in self.results)
        return round(earned / total, 4)

    def by_tag(self) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for result in self.results:
            for tag in result.tags or ("untagged",):
                bucket = buckets.setdefault(tag, {"cases": 0, "passed": 0, "score": 0.0})
                bucket["cases"] += 1
                bucket["passed"] += 1 if result.passed else 0
                bucket["score"] += result.score
        for bucket in buckets.values():
            bucket["score"] = round(bucket["score"] / bucket["cases"], 4)
            bucket["pass_rate"] = round(bucket["passed"] / bucket["cases"], 4)
        return buckets

    def failures(self) -> list[CaseResult]:
        return [result for result in self.results if not result.passed]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cases": len(self.results),
            "pass_rate": self.pass_rate(),
            "weighted_score": self.weighted_score(),
            "threshold": self.threshold,
            "by_tag": self.by_tag(),
            "failures": [result.case_id for result in self.failures()],
        }


class EvalSuite:
    """Runs graded cases against a solver with partial-credit scoring."""

    def __init__(self, cases: Iterable[EvalCase], threshold: float = 0.8) -> None:
        self.cases = list(cases)
        if not self.cases:
            raise ValueError("an eval suite needs at least one case")
        self.threshold = threshold

    def run(self, solver: Callable[[EvalCase], str | tuple[float, str]]) -> EvalReport:
        results: list[CaseResult] = []
        weights: dict[str, float] = {}
        for case in self.cases:
            weights[case.case_id] = case.weight
            raw = solver(case)
            detail = ""
            if isinstance(raw, tuple):
                score, detail = float(raw[0]), str(raw[1])
                output = detail
            else:
                output = str(raw)
                score = token_overlap(case.expected, output)
            score = round(max(0.0, min(1.0, score)), 4)
            results.append(CaseResult(
                case_id=case.case_id, passed=score >= self.threshold,
                score=score, output=output, detail=detail, tags=case.tags))
        return EvalReport(results=results, threshold=self.threshold, weights=weights)


# ── Harness audit ─────────────────────────────────────────────────────────

HARNESS_PRIMITIVES: list[tuple[str, str, str]] = [
    ("agent-loop", "Bounded reason/act loop with explicit stop conditions",
     "the agent never terminates, or terminates before the task is done"),
    ("planning", "Plan and task decomposition with dependencies",
     "long tasks wander and lose track of the remaining work"),
    ("context-assembly", "Deliberate context delivery per step",
     "the model sees a random dump instead of the relevant state"),
    ("compaction", "Compaction under a token budget with measured retention",
     "context rot: quality degrades as the window fills"),
    ("tool-design", "Typed tool contracts with validation",
     "malformed calls become silent failures"),
    ("skills", "Packaged skills / procedures the agent can load",
     "the agent re-invents procedures on every run"),
    ("permissions", "Structured permissions and capability rules",
     "authorization relies on prompt wording alone"),
    ("memory", "Durable state and checkpoints across steps",
     "progress is lost whenever a run restarts"),
    ("orchestration", "Task runners and batch scheduling",
     "parallel work collides or serialises accidentally"),
    ("verification", "Verification loops with CI-grade checks",
     "the agent declares success without evidence"),
    ("observability", "Tracing and span-level metrics",
     "failures cannot be attributed to a step"),
    ("debugging", "Replayable runs and state diffs",
     "the same bug cannot be reproduced"),
    ("human-in-the-loop", "Approval and interrupt handling",
     "risky actions happen without consent"),
    ("evaluation", "Offline evals with graded scoring",
     "improvements are judged by vibes, not measurements"),
]

PRIMITIVE_WEIGHTS: dict[str, float] = {
    "agent-loop": 2.0,
    "permissions": 2.0,
    "verification": 2.0,
    "observability": 1.5,
    "compaction": 1.5,
    "planning": 1.5,
}


@dataclass
class HarnessReview:
    present: list[str]
    missing: list[str]
    score: float
    grade: str
    recommendations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"present": self.present, "missing": self.missing,
                "score": self.score, "grade": self.grade,
                "recommendations": self.recommendations}


class HarnessBlueprint:
    """Grades an agent build against the fourteen harness concerns."""

    def __init__(self, primitives: list[tuple[str, str, str]] = HARNESS_PRIMITIVES,
                 weights: dict[str, float] | None = None) -> None:
        self.primitives = list(primitives)
        self.weights = dict(PRIMITIVE_WEIGHTS)
        self.weights.update(weights or {})

    def audit(self, present: Iterable[str]) -> HarnessReview:
        supplied = set(present)
        known = {key for key, _, _ in self.primitives}
        unknown = supplied - known
        if unknown:
            raise ValueError(f"unknown primitives: {', '.join(sorted(unknown))}")
        present_keys = [key for key, _, _ in self.primitives if key in supplied]
        missing = [(key, title, why) for key, title, why in self.primitives
                   if key not in supplied]
        total = sum(self.weights.get(key, 1.0) for key in known)
        earned = sum(self.weights.get(key, 1.0) for key in present_keys)
        score = round(earned / total, 4) if total else 0.0
        if score >= 0.9:
            grade = "A"
        elif score >= 0.75:
            grade = "B"
        elif score >= 0.55:
            grade = "C"
        else:
            grade = "D"
        recommendations = [
            f"Add {key}: {title.lower()} — without it {why}"
            for key, title, why in sorted(
                missing, key=lambda item: -self.weights.get(item[0], 1.0))
        ]
        return HarnessReview(present=present_keys, missing=[key for key, _, _ in missing],
                             score=score, grade=grade, recommendations=recommendations)

    def checklist(self) -> str:
        return "\n".join(f"[ ] {key}: {title}" for key, title, _ in self.primitives)


# ── Agent loop ────────────────────────────────────────────────────────────

@dataclass
class LoopAction:
    """One decision produced by the policy."""

    kind: str = "tool"                 # tool | respond | stop | escalate
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("tool", "respond", "stop", "escalate"):
            raise ValueError(f"unknown action kind {self.kind!r}")

    def signature(self) -> tuple[Any, ...]:
        return (self.kind, self.tool,
                tuple(sorted((str(k), str(v)) for k, v in self.arguments.items())))

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "tool": self.tool,
                "arguments": dict(self.arguments), "text": self.text}


@dataclass
class LoopStep:
    index: int
    action: LoopAction
    observation: str
    tokens: int
    allowed: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "action": self.action.as_dict(),
                "observation": self.observation, "tokens": self.tokens,
                "allowed": self.allowed}


@dataclass
class LoopResult:
    task: str
    steps: list[LoopStep]
    stop_reason: str
    tokens_used: int
    succeeded: bool
    final_text: str = ""
    denials: int = 0
    approvals: list[ApprovalRequest] = field(default_factory=list)

    def observations(self) -> list[str]:
        return [step.observation for step in self.steps]

    def tool_sequence(self) -> list[str]:
        return [step.action.tool for step in self.steps if step.action.kind == "tool"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "stop_reason": self.stop_reason,
            "succeeded": self.succeeded,
            "tokens_used": self.tokens_used,
            "steps": [step.as_dict() for step in self.steps],
            "denials": self.denials,
            "final_text": self.final_text,
        }


class AgentLoop:
    """A bounded reason/act loop with real guard rails."""

    STOP_REASONS = ("final_answer", "policy_stop", "max_steps", "budget_exhausted",
                    "loop_detected", "approval_required", "no_action")

    def __init__(self, registry: ToolRegistry | None = None,
                 gate: PermissionGate | None = None,
                 approvals: HumanApprovalQueue | None = None,
                 max_steps: int = 8, budget: int = 6000) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if budget <= 0:
            raise ValueError("budget must be positive")
        self.registry = registry or default_registry()
        self.gate = gate
        self.approvals = approvals
        self.max_steps = max_steps
        self.budget = budget

    def run(self, task: str, policy: Callable[[str, list[LoopStep]], LoopAction]
            ) -> LoopResult:
        steps: list[LoopStep] = []
        used = estimate_tokens(task)
        last_signature: tuple[Any, ...] | None = None
        repeats = 0
        denials = 0
        approvals: list[ApprovalRequest] = []
        stop_reason = "max_steps"
        final_text = ""
        succeeded = False

        for index in range(1, self.max_steps + 1):
            if used >= self.budget:
                stop_reason = "budget_exhausted"
                break
            try:
                action = policy(task, steps)
            except Exception as exc:
                stop_reason = "no_action"
                steps.append(LoopStep(index, LoopAction(kind="stop"),
                                      f"policy error: {type(exc).__name__}: {exc}", 0))
                break
            if action is None:
                stop_reason = "no_action"
                break

            signature = action.signature()
            repeats = repeats + 1 if signature == last_signature else 0
            last_signature = signature
            if repeats >= 1:
                steps.append(LoopStep(index, action, "repeated action suppressed", 0))
                stop_reason = "loop_detected"
                break

            if action.kind == "respond":
                final_text = action.text
                stop_reason = "final_answer"
                succeeded = True
                steps.append(LoopStep(index, action, action.text,
                                      estimate_tokens(action.text)))
                break
            if action.kind == "stop":
                stop_reason = "policy_stop"
                break
            if action.kind == "escalate":
                interrupt_text = action.text or "escalation requested"
                step_tokens = estimate_tokens(interrupt_text)
                used += step_tokens
                steps.append(LoopStep(index, action, interrupt_text, step_tokens))
                stop_reason = "approval_required"
                break

            # tool action
            if self.gate is not None:
                decision = self.gate.decide(action.tool, action.arguments)
                if decision.requires_approval:
                    if self.approvals is not None:
                        request = self.approvals.submit(
                            action.tool, action.arguments, decision.risk, decision.reason)
                        approvals.append(request)
                    observation = f"approval required: {decision.reason}"
                    step_tokens = estimate_tokens(observation)
                    used += step_tokens
                    steps.append(LoopStep(index, action, observation, step_tokens, False))
                    stop_reason = "approval_required"
                    break
                if not decision.allowed:
                    denials += 1
                    observation = f"denied: {decision.reason}"
                    step_tokens = estimate_tokens(observation)
                    used += step_tokens
                    steps.append(LoopStep(index, action, observation, step_tokens, False))
                    if used >= self.budget:
                        stop_reason = "budget_exhausted"
                        break
                    continue

            result = self.registry.call(action.tool, action.arguments)
            observation = result.observation()
            step_tokens = result.cost + estimate_tokens(observation) + estimate_tokens(str(action.arguments))
            used += step_tokens
            steps.append(LoopStep(index, action, observation, step_tokens, result.ok))
        else:
            stop_reason = "max_steps"

        return LoopResult(task=task, steps=steps, stop_reason=stop_reason,
                          tokens_used=used, succeeded=succeeded, final_text=final_text,
                          denials=denials, approvals=approvals)


# ── Facade ────────────────────────────────────────────────────────────────

class HarnessEngine:
    """One entry point for planning, compaction, looping, verification and evals."""

    def __init__(self, registry: ToolRegistry | None = None,
                 gate: PermissionGate | None = None,
                 budget: ContextBudget | None = None) -> None:
        self.registry = registry or default_registry()
        self.gate = gate or PermissionGate(registry=self.registry)
        self.budget = budget or ContextBudget()
        self.approvals = HumanApprovalQueue()
        self.state = StateStore()
        self.tracer = Tracer()
        self.human = HumanInterface()
        self.blueprint = HarnessBlueprint()

    # planning
    def plan(self, goal: str, steps: Iterable[str | Subtask | dict[str, Any]]) -> dict[str, Any]:
        return TaskDecomposer().decompose(goal, steps).as_dict()

    def schedule(self, plan: Plan, batch_tokens: int = 400) -> list[list[str]]:
        return TaskDecomposer().split_by_budget(plan, batch_tokens)

    # context
    def compact(self, messages: Iterable[Message], strategy: str = "summarise",
                query: str = "") -> CompactionResult:
        compactor = ContextCompactor(self.budget, strategy=strategy)
        return compactor.compact_until_fits(messages, query)

    # execution
    def loop(self, task: str, policy: Callable[[str, list[LoopStep]], LoopAction],
             registry: ToolRegistry | None = None, max_steps: int = 8) -> LoopResult:
        loop = AgentLoop(registry=registry or self.registry, gate=self.gate,
                         approvals=self.approvals, max_steps=max_steps,
                         budget=self.budget.available())
        return loop.run(task, policy)

    # verification
    def verify(self, artifact: str, checks: Iterable[Check],
               revise: Callable[[str, list[str]], str] | None = None,
               max_attempts: int = 3) -> VerificationReport:
        return VerificationLoop(checks, max_attempts=max_attempts).run(artifact, revise)

    # evals
    def evaluate(self, cases: Iterable[EvalCase],
                 solver: Callable[[EvalCase], str | tuple[float, str]],
                 threshold: float = 0.8) -> dict[str, Any]:
        return EvalSuite(cases, threshold=threshold).run(solver).as_dict()

    # audit
    def audit(self, present: Iterable[str]) -> dict[str, Any]:
        return self.blueprint.audit(present).as_dict()

    def describe(self) -> dict[str, Any]:
        return {
            "tools": self.registry.names(),
            "rules": len(self.gate.rules),
            "window": self.budget.window,
            "available_tokens": self.budget.available(),
            "primitives": [key for key, _, _ in HARNESS_PRIMITIVES],
            "stop_reasons": list(AgentLoop.STOP_REASONS),
        }

    def run(self, task: str, policy: Callable[[str, list[LoopStep]], LoopAction],
            **kwargs: Any) -> LoopResult:
        return self.loop(task, policy, **kwargs)


engine = HarnessEngine()
