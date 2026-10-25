"""
FRIDAY/apps/core/src/friday_core/real_browser_agent.py — Real Browser Agent.

A working browser-automation core for FRIDAY: it turns a page into an indexed,
agent-readable interactive tree, resolves element selectors, drives navigation,
forms and tabs, and runs a goal-directed action loop over a page graph.

Real working implementations:
- BoundingBox: viewport / geometry math
- BrowserNode + DomTreeBuilder: real DOM tree construction, visibility
  inheritance, accessible-name resolution, interactivity detection
- DomSerializer: compact indexed serialization for LLM consumption
- SelectorIndex: index / text / role / label / path resolution
- PageState + BrowserSession: history, tabs, scrolling, click/type/keys
- SensitiveDataGuard: classification of credential / payment / identity fields
- FormFiller: labelled form filling with per-field validation
- DataExtractor: schema-driven structured extraction from the tree
- BrowserAgent: deterministic goal-directed workflow loop with loop detection
- SessionRecorder: action log + replay verification
"""
from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


# ── Geometry ──────────────────────────────────────────────────────────────

@dataclass
class BoundingBox:
    """A rectangle in page coordinates (CSS pixels)."""

    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def intersects(self, other: "BoundingBox") -> bool:
        """True when the two rectangles overlap by a non-zero area."""
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx > 0 and dy > 0

    def intersection_area(self, other: "BoundingBox") -> float:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        if dx <= 0 or dy <= 0:
            return 0.0
        return dx * dy

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px <= self.right and self.y <= py <= self.bottom

    def visible_area_in(self, viewport: "BoundingBox") -> float:
        """Portion of this box that is inside ``viewport``."""
        return self.intersection_area(viewport)

    def visible_ratio(self, viewport: "BoundingBox") -> float:
        if self.area <= 0:
            return 0.0
        return self.visible_area_in(viewport) / self.area

    def scroll_by(self, dy: float) -> "BoundingBox":
        return BoundingBox(self.x, self.y - dy, self.width, self.height)

    def as_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "width": round(self.width, 2),
            "height": round(self.height, 2),
        }


# ── DOM tree ──────────────────────────────────────────────────────────────

INTERACTIVE_TAGS = {
    "a", "button", "input", "select", "textarea", "option", "summary",
    "details", "label", "audio", "video",
}

ACTION_ROLES = {
    "button", "link", "checkbox", "radio", "textbox", "combobox",
    "menuitem", "tab", "switch", "searchbox", "slider", "option",
    "spinbutton", "listbox", "menu",
}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Attribute keys kept in the serialized view. Everything else is noise.
KEPT_ATTRIBUTES = (
    "id", "href", "name", "type", "placeholder", "aria-label", "title",
    "value", "alt", "role", "for", "action", "method", "checked", "disabled",
)


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


@dataclass
class BrowserNode:
    """One node of a serialized page tree."""

    node_id: int
    tag: str
    path: str
    depth: int
    text: str = ""
    role: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    bounds: BoundingBox | None = None
    parent_id: int | None = None
    children: list["BrowserNode"] = field(default_factory=list)
    is_visible: bool = True
    is_interactive: bool = False
    aria_hidden: bool = False
    derived_role: str = ""

    @property
    def accessible_name(self) -> str:
        """ARIA-style name resolution: aria-label > label > text > placeholder."""
        for key in ("aria-label", "label", "placeholder", "alt", "title", "name"):
            value = self.attributes.get(key, "")
            if value:
                return _norm_ws(value)
        if self.text:
            return _norm_ws(self.text)[:120]
        value = self.attributes.get("value", "")
        return _norm_ws(value)[:120]

    @property
    def input_type(self) -> str:
        return self.attributes.get("type", "text").lower() if self.tag == "input" else ""

    @property
    def is_disabled(self) -> bool:
        return "disabled" in self.attributes

    @property
    def action_kind(self) -> str:
        """What this node does when activated."""
        tag = self.tag
        if tag == "input":
            itype = self.input_type or "text"
            if itype in ("checkbox", "radio"):
                return itype
            if itype == "submit":
                return "submit"
            return "input"
        if tag == "select":
            return "select"
        if tag == "textarea":
            return "input"
        if tag == "a":
            return "link"
        if tag in ("button", "summary"):
            if self.attributes.get("type", "").lower() == "submit":
                return "submit"
            return "click"
        role = self.derived_role
        if role in ("button", "menuitem", "tab", "switch"):
            return "click"
        if role == "link":
            return "link"
        if role in ("textbox", "searchbox", "spinbutton"):
            return "input"
        return "click" if self.is_interactive else "none"

    def walk(self) -> Iterable["BrowserNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


class DomTreeBuilder:
    """Build a real DOM tree from a declarative page description.

    A page spec is a nested dict::

        {"tag": "body", "children": [
            {"tag": "h1", "text": "Pricing"},
            {"tag": "a", "attrs": {"href": "/docs"}, "text": "Docs",
             "bounds": [0, 40, 80, 20]},
        ]}
    """

    def __init__(self, viewport: BoundingBox | None = None) -> None:
        self.viewport = viewport or BoundingBox(0, 0, 1280, 720)
        self._next_id = 1

    def build(self, spec: dict[str, Any]) -> BrowserNode:
        self._next_id = 1
        return self._build(spec, depth=0, parent=None, parent_path="", parent_visible=True)

    def _build(
        self,
        spec: dict[str, Any],
        depth: int,
        parent: BrowserNode | None,
        parent_path: str,
        parent_visible: bool,
    ) -> BrowserNode:
        tag = (spec.get("tag") or spec.get("role") or "div").lower()
        attrs = {str(k).lower(): str(v) for k, v in (spec.get("attrs") or {}).items()}
        node_id = self._next_id
        self._next_id += 1

        path = f"{parent_path}>{tag}" if parent_path else tag
        if attrs.get("id"):
            path += f"#{attrs['id']}"

        raw_bounds = spec.get("bounds")
        bounds = None
        if raw_bounds:
            bounds = BoundingBox(
                float(raw_bounds[0]), float(raw_bounds[1]),
                float(raw_bounds[2]), float(raw_bounds[3]),
            )

        style = attrs.get("style", "").replace(" ", "").lower()
        aria_hidden = attrs.get("aria-hidden", "").lower() in ("true", "1")
        own_visible = True
        if "display:none" in style or "visibility:hidden" in style:
            own_visible = False
        if "opacity:0" in style or "opacity:0.0" in style:
            own_visible = False
        if "hidden" in attrs and attrs["hidden"].lower() in ("", "true", "1", "hidden"):
            own_visible = False
        if bounds is not None and (bounds.width <= 0 or bounds.height <= 0):
            own_visible = False

        node = BrowserNode(
            node_id=node_id,
            tag=tag,
            path=path,
            depth=depth,
            text=_norm_ws(spec.get("text", "")),
            role=attrs.get("role", "").lower(),
            attributes=attrs,
            bounds=bounds,
            parent_id=parent.node_id if parent else None,
            is_visible=own_visible and parent_visible,
            aria_hidden=aria_hidden,
        )
        node.derived_role = node.role or self._infer_role(node)

        for child_spec in spec.get("children", []) or []:
            child = self._build(
                child_spec, depth + 1, node, path.replace(f"#{attrs['id']}", "") if attrs.get("id") else path,
                node.is_visible,
            )
            node.children.append(child)

        node.is_interactive = self._is_interactive(node)
        return node

    @staticmethod
    def _infer_role(node: BrowserNode) -> str:
        if node.tag == "a":
            return "link"
        if node.tag == "button":
            return "button"
        if node.tag == "select":
            return "combobox"
        if node.tag == "textarea":
            return "textbox"
        if node.tag in HEADING_TAGS:
            return "heading"
        if node.tag == "input":
            itype = node.input_type or "text"
            return {
                "checkbox": "checkbox",
                "radio": "radio",
                "submit": "button",
                "button": "button",
                "search": "searchbox",
                "number": "spinbutton",
                "range": "slider",
            }.get(itype, "textbox")
        if node.tag == "label":
            return "label"
        return ""

    def _is_interactive(self, node: BrowserNode) -> bool:
        if node.is_disabled or not node.is_visible:
            return False
        if node.tag in INTERACTIVE_TAGS:
            return True
        if node.derived_role in ACTION_ROLES:
            return True
        if node.attributes.get("onclick"):
            return True
        if node.attributes.get("tabindex", "").isdigit() and int(node.attributes["tabindex"]) >= 0:
            return bool(node.accessible_name or node.text)
        return False


# ── Serializer ────────────────────────────────────────────────────────────

@dataclass
class SerializeConfig:
    """Tuning knobs for the agent-facing text view of a page."""

    max_interactive: int = 120
    max_text_chars: int = 120
    include_text_nodes: bool = True
    viewport_only: bool = True
    max_depth: int = 24


class DomSerializer:
    """Serialize a page tree into compact, index-addressable text.

    Output resembles the real browser-agent format::

        [0]<body>  (page 1280x720, scroll 0/1800)
        | [3]<input type=search placeholder="Search docs" />
        | [4]<button>Search</button>
    """

    def __init__(self, config: SerializeConfig | None = None) -> None:
        self.config = config or SerializeConfig()

    def select_nodes(self, root: BrowserNode, viewport: BoundingBox) -> list[BrowserNode]:
        """Choose the interactive nodes worth showing, ranked by salience."""
        candidates: list[BrowserNode] = []
        for node in root.walk():
            if not node.is_visible or node.aria_hidden:
                continue
            if self.config.viewport_only and node.bounds is not None:
                if node.bounds.visible_area_in(viewport) <= 0:
                    continue
            if node.is_interactive:
                candidates.append(node)
            elif self.config.include_text_nodes and node.text and node.tag in (
                HEADING_TAGS | {"p", "li", "td", "th", "span", "div", "strong", "code"}
            ):
                candidates.append(node)

        interactive = [n for n in candidates if n.is_interactive]
        if len(interactive) > self.config.max_interactive:
            keep = set(
                n.node_id
                for n in sorted(interactive, key=lambda n: self.salience(n, viewport), reverse=True)[
                    : self.config.max_interactive
                ]
            )
            candidates = [n for n in candidates if not n.is_interactive or n.node_id in keep]
        return sorted(candidates, key=lambda n: (n.depth, n.node_id))

    @staticmethod
    def salience(node: BrowserNode, viewport: BoundingBox) -> float:
        """Rank elements by how likely they are to be the intended target."""
        score = 0.0
        if node.bounds is not None:
            ratio = node.bounds.visible_ratio(viewport)
            score += 2.0 * ratio
            area = node.bounds.area
            if area > 0:
                score += min(1.0, 20000.0 / area)
            # Above the fold is more prominent.
            score += 0.5 if node.bounds.y < viewport.height * 0.5 else 0.0
        if node.is_interactive:
            score += 1.0
        if node.accessible_name:
            score += 0.5
        score -= 0.02 * node.depth
        return round(score, 4)

    def _format_attributes(self, node: BrowserNode) -> str:
        parts = []
        for key in KEPT_ATTRIBUTES:
            if key in node.attributes and node.attributes[key]:
                value = node.attributes[key]
                if len(value) > 60:
                    value = value[:57] + "..."
                parts.append(f'{key}="{value}"')
        return (" " + " ".join(parts)) if parts else ""

    def _format_line(self, node: BrowserNode) -> str:
        attrs = self._format_attributes(node)
        if node.is_interactive:
            label = node.accessible_name[: self.config.max_text_chars]
            prefix = "| " * max(0, min(node.depth, 8))
            if node.tag in ("input", "select", "textarea"):
                return f"{prefix}[{node.node_id}]<{node.tag}{attrs} />"
            inner = f">{label}</{node.tag}>" if label else "/>"
            return f"{prefix}[{node.node_id}]<{node.tag}{attrs}{inner}"
        text = node.text[: self.config.max_text_chars]
        prefix = "| " * max(0, min(node.depth, 8))
        return f"{prefix}  <{node.tag}>{text}</{node.tag}>"

    def serialize(self, state: "PageState") -> str:
        root = state.root
        header = (
            f"url={state.url} title={state.title!r} "
            f"viewport={int(state.viewport.width)}x{int(state.viewport.height)} "
            f"scroll={int(state.scroll_y)}/{int(max(0.0, state.doc_height - state.viewport.height))} "
            f"tabs={len(state.tabs)} active_tab={state.tab_id}"
        )
        if root is None:
            return header + "\n(empty page)"
        nodes = self.select_nodes(root, state.viewport_at_scroll())
        lines = [header, f"[{root.node_id}]<{root.tag}>"]
        lines.extend(self._format_line(n) for n in nodes if n.node_id != root.node_id)
        return "\n".join(lines)

    def token_estimate(self, text: str) -> int:
        """Cheap token estimate used for context budgeting."""
        return max(1, math.ceil(len(text) / 4.0))


# ── Selectors ─────────────────────────────────────────────────────────────

@dataclass
class SelectorQuery:
    """A structured element query."""

    text: str = ""
    role: str = ""
    tag: str = ""
    name: str = ""
    href_contains: str = ""
    nth: int = 0

    def describe(self) -> str:
        bits = [f"{k}={v!r}" for k, v in vars(self).items() if v not in ("", 0)]
        return " ".join(bits) or "<any>"


class SelectorIndex:
    """Resolve elements by index, text, role, label or CSS-ish path."""

    def __init__(self, root: BrowserNode | None) -> None:
        self.nodes: dict[int, BrowserNode] = {}
        self.by_tag: dict[str, list[BrowserNode]] = {}
        self.by_role: dict[str, list[BrowserNode]] = {}
        self.by_label: dict[str, list[BrowserNode]] = {}
        if root is not None:
            for node in root.walk():
                if not node.is_visible:
                    continue
                self.nodes[node.node_id] = node
                self.by_tag.setdefault(node.tag, []).append(node)
                if node.derived_role:
                    self.by_role.setdefault(node.derived_role, []).append(node)
                label = node.accessible_name.lower()
                if label:
                    self.by_label.setdefault(label, []).append(node)

    def by_index(self, index: int) -> BrowserNode | None:
        return self.nodes.get(index)

    def all(self) -> list[BrowserNode]:
        return sorted(self.nodes.values(), key=lambda n: n.node_id)

    def interactive(self) -> list[BrowserNode]:
        return [n for n in self.all() if n.is_interactive]

    def by_text(self, text: str, exact: bool = False) -> list[BrowserNode]:
        needle = _norm_ws(text).lower()
        if not needle:
            return []
        if exact:
            return [n for n in self.all() if _norm_ws(n.accessible_name).lower() == needle]
        out = []
        for node in self.all():
            hay = f"{node.accessible_name} {node.text}".lower()
            if needle in hay:
                out.append(node)
        return out

    def by_path(self, path: str) -> list[BrowserNode]:
        """Match a path suffix, e.g. ``form#login>input``."""
        needle = path.replace(" ", "").lower()
        return [n for n in self.all() if n.path.lower().endswith(needle)]

    def query(self, q: SelectorQuery) -> list[BrowserNode]:
        """Intersect the selector fields, preserving document order."""
        pool = self.all()
        if q.tag:
            pool = [n for n in pool if n.tag == q.tag.lower()]
        if q.role:
            pool = [n for n in pool if n.derived_role == q.role.lower()]
        if q.name:
            needle = q.name.lower()
            pool = [n for n in pool if needle in n.accessible_name.lower()]
        if q.href_contains:
            needle = q.href_contains.lower()
            pool = [n for n in pool if needle in n.attributes.get("href", "").lower()]
        if q.text:
            needle = q.text.lower()
            pool = [n for n in pool if needle in f"{n.accessible_name} {n.text}".lower()]
        return pool

    def first(self, q: SelectorQuery) -> BrowserNode | None:
        hits = self.query(q)
        if not hits:
            return None
        idx = min(q.nth, len(hits) - 1)
        return hits[idx]


# ── Page / session ────────────────────────────────────────────────────────

@dataclass
class TabState:
    """One open browser tab."""

    tab_id: str
    url: str
    title: str
    history: list[str] = field(default_factory=list)
    forward: list[str] = field(default_factory=list)
    scroll_y: float = 0.0
    root: BrowserNode | None = None
    viewport: BoundingBox = field(default_factory=lambda: BoundingBox(0, 0, 1280, 720))

    def navigate(self, url: str) -> None:
        if self.url:
            self.history.append(self.url)
        self.url = url
        self.forward.clear()
        self.scroll_y = 0.0


@dataclass
class PageState:
    """Snapshot of what the agent currently sees."""

    url: str
    title: str
    root: BrowserNode | None
    viewport: BoundingBox
    scroll_y: float
    doc_height: float
    tab_id: str
    tabs: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def viewport_at_scroll(self) -> BoundingBox:
        return BoundingBox(0.0, self.scroll_y, self.viewport.width, self.viewport.height)

    @property
    def above_the_fold(self) -> list[BrowserNode]:
        box = self.viewport_at_scroll()
        if self.root is None:
            return []
        return [
            n for n in self.root.walk()
            if n.is_visible and n.bounds is not None
            and n.bounds.visible_area_in(box) > 0
        ]


@dataclass
class ActionResult:
    """Outcome of a single browser action."""

    ok: bool
    action: str
    detail: str = ""
    url: str = ""
    node_id: int | None = None
    blocked: str = ""
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "detail": self.detail,
            "url": self.url,
            "node_id": self.node_id,
            "blocked": self.blocked,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass
class ActionRecord:
    """Audit record for one executed action."""

    seq: int
    action: str
    target: str
    payload: str
    url_before: str
    url_after: str
    ok: bool
    ts: float = field(default_factory=time.time)


# ── Sensitive data guard ──────────────────────────────────────────────────

SENSITIVE_PATTERNS = {
    "password": (r"pass(word|phrase)?", r"pin", r"secret"),
    "payment": (r"card", r"cvv", r"cvc", r"iban", r"account.?number", r"routing"),
    "identity": (r"ssn", r"social.?security", r"passport", r"aadhaar", r"national.?id", r"dob"),
    "secret": (r"api.?key", r"token", r"private.?key", r"seed.?phrase", r"otp"),
}


class SensitiveDataGuard:
    """Classify inputs that must never be typed without explicit approval."""

    def __init__(self, approve_levels: Iterable[str] = ()) -> None:
        self.approved = set(approve_levels)

    @staticmethod
    def classify(node: BrowserNode) -> str:
        hay = " ".join([
            node.attributes.get("name", ""),
            node.attributes.get("id", ""),
            node.attributes.get("placeholder", ""),
            node.attributes.get("aria-label", ""),
            node.attributes.get("autocomplete", ""),
            node.accessible_name,
        ]).lower()
        if node.tag == "input" and node.input_type == "password":
            return "password"
        for level, patterns in SENSITIVE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, hay):
                    return level
        return ""

    def check(self, node: BrowserNode) -> str:
        """Return '' when allowed, otherwise the blocking reason."""
        level = self.classify(node)
        if not level:
            return ""
        if level in self.approved:
            return ""
        return f"sensitive field ({level}) requires explicit approval"

    @staticmethod
    def redact(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "*" * len(value)
        return value[:2] + "*" * (len(value) - 4) + value[-2:]


# ── Browser session ───────────────────────────────────────────────────────

@dataclass
class SitePage:
    """A page the simulated browser can load from the site graph."""

    url: str
    title: str
    spec: dict[str, Any]
    doc_height: float = 1800.0
    requires_auth: bool = False


class BrowserSession:
    """Drive a multi-tab browser over a site graph, deterministically."""

    def __init__(
        self,
        site: dict[str, SitePage] | None = None,
        viewport: tuple[float, float] = (1280, 720),
        guard: SensitiveDataGuard | None = None,
    ) -> None:
        self.site = site or {}
        self.viewport_size = viewport
        self.guard = guard or SensitiveDataGuard()
        self.tabs: dict[str, TabState] = {}
        self.active_tab: str = ""
        self.actions: list[ActionRecord] = []
        self.serializer = DomSerializer()
        self._seq = 0

    # ── tab management ────────────────────────────────────────────────

    def new_tab(self, url: str) -> str:
        tab_id = f"tab-{len(self.tabs) + 1}-{uuid.uuid4().hex[:4]}"
        tab = TabState(tab_id=tab_id, url="", title="", viewport=BoundingBox(0, 0, *self.viewport_size))
        self.tabs[tab_id] = tab
        self.active_tab = tab_id
        self.open(url)
        return tab_id

    def switch_tab(self, tab_id: str) -> bool:
        if tab_id not in self.tabs:
            return False
        self.active_tab = tab_id
        return True

    def close_tab(self, tab_id: str) -> bool:
        if tab_id not in self.tabs or len(self.tabs) <= 1:
            return False
        del self.tabs[tab_id]
        if self.active_tab == tab_id:
            self.active_tab = next(iter(self.tabs))
        return True

    @property
    def tab(self) -> TabState:
        if not self.tabs:
            tab_id = f"tab-1-{uuid.uuid4().hex[:4]}"
            self.tabs[tab_id] = TabState(
                tab_id=tab_id, url="", title="",
                viewport=BoundingBox(0, 0, *self.viewport_size),
            )
            self.active_tab = tab_id
        if not self.active_tab:
            self.active_tab = next(iter(self.tabs))
        return self.tabs[self.active_tab]

    # ── navigation ────────────────────────────────────────────────────

    def open(self, url: str) -> ActionResult:
        t0 = time.time()
        page = self.site.get(url)
        tab = self.tab
        tab.navigate(url)
        if page is None:
            tab.title = url
            tab.root = None
            return self._record("open", url, "", True, f"no page registered for {url}", t0)
        builder = DomTreeBuilder(BoundingBox(0, 0, *self.viewport_size))
        tab.root = builder.build(page.spec)
        tab.title = page.title
        tab.doc_height = page.doc_height
        return self._record("open", url, "", True, page.title, t0)

    def back(self) -> ActionResult:
        t0 = time.time()
        tab = self.tab
        if not tab.history:
            return self._record("back", "", "", False, "no history", t0)
        tab.forward.append(tab.url)
        prev = tab.history.pop()
        page = self.site.get(prev)
        tab.url = prev
        tab.scroll_y = 0.0
        if page is not None:
            tab.root = DomTreeBuilder(BoundingBox(0, 0, *self.viewport_size)).build(page.spec)
            tab.title = page.title
            tab.doc_height = page.doc_height
        return self._record("back", prev, "", True, tab.title, t0)

    def forward_page(self) -> ActionResult:
        t0 = time.time()
        tab = self.tab
        if not tab.forward:
            return self._record("forward", "", "", False, "no forward history", t0)
        nxt = tab.forward.pop()
        tab.history.append(tab.url)
        page = self.site.get(nxt)
        tab.url = nxt
        tab.scroll_y = 0.0
        if page is not None:
            tab.root = DomTreeBuilder(BoundingBox(0, 0, *self.viewport_size)).build(page.spec)
            tab.title = page.title
            tab.doc_height = page.doc_height
        return self._record("forward", nxt, "", True, tab.title, t0)

    # ── interaction ───────────────────────────────────────────────────

    def index(self) -> SelectorIndex:
        return SelectorIndex(self.tab.root)

    def scroll(self, dy: float) -> ActionResult:
        t0 = time.time()
        tab = self.tab
        max_scroll = max(0.0, tab.doc_height - self.viewport_size[1])
        before = tab.scroll_y
        tab.scroll_y = min(max_scroll, max(0.0, tab.scroll_y + dy))
        moved = tab.scroll_y - before
        return self._record("scroll", "", f"dy={dy}", moved != 0, f"scroll {tab.scroll_y:.0f}", t0)

    def scroll_into_view(self, node: BrowserNode) -> bool:
        if node.bounds is None:
            return False
        tab = self.tab
        top, bottom = node.bounds.y, node.bounds.bottom
        if top < tab.scroll_y:
            tab.scroll_y = max(0.0, top - 24)
            return True
        if bottom > tab.scroll_y + self.viewport_size[1]:
            tab.scroll_y = min(
                max(0.0, tab.doc_height - self.viewport_size[1]),
                bottom - self.viewport_size[1] + 24,
            )
            return True
        return False

    def click(self, node_id: int) -> ActionResult:
        t0 = time.time()
        tab = self.tab
        node = self.index().by_index(node_id)
        if node is None:
            return self._record("click", str(node_id), "", False, "element not found", t0)
        if node.is_disabled:
            return self._record("click", node.accessible_name, "", False, "element disabled", t0)
        self.scroll_into_view(node)
        url_before = tab.url

        if node.action_kind in ("checkbox", "radio"):
            node.attributes["checked"] = "" if "checked" in node.attributes else "true"
            node.attributes.setdefault("checked", "true")
            return self._record("click", node.accessible_name, node.action_kind, True, "toggled", t0)

        if node.action_kind == "link":
            href = node.attributes.get("href", "")
            if href.startswith("#"):
                return self._record("click", node.accessible_name, href, True, "anchor", t0)
            target = href if href.startswith("http") else self._resolve_url(href)
            self._record("click", node.accessible_name, href, True, f"navigate -> {target}", t0,
                         url=target)
            return self.open(target)

        if node.tag == "option":
            parent = self._parent_select(node)
            if parent is not None:
                parent.attributes["value"] = node.attributes.get("value", node.text)
            return self._record("click", node.accessible_name, "", True, "option selected", t0)

        if node.action_kind == "submit":
            form = self._first_form()
            if form is not None:
                action = form.attributes.get("action", "")
                if action:
                    target_url = self._resolve_url(action)
                    if target_url in self.site:
                        self._record("click", node.accessible_name, action, True,
                                     f"submit -> {target_url}", t0, url=target_url)
                        return self.open(target_url)

        # Generic click: honour a data-next / onclick navigation hint.
        next_url = node.attributes.get("data-next", "")
        if next_url:
            target_url = self._resolve_url(next_url)
            self._record("click", node.accessible_name, next_url, True,
                         f"navigate -> {target_url}", t0, url=target_url)
            return self.open(target_url)
        return self._record("click", node.accessible_name, "", True, "clicked (no navigation)",
                            t0, url=url_before)

    def _parent_select(self, node: BrowserNode) -> BrowserNode | None:
        root = self.tab.root
        if root is None:
            return None
        for candidate in root.walk():
            if any(c.node_id == node.node_id for c in candidate.children) and candidate.tag == "select":
                return candidate
        return None

    def _resolve_url(self, href: str) -> str:
        if href.startswith("http") or href.startswith("about:"):
            return href
        base = self.tab.url or ""
        if base.endswith("/"):
            base = base.rstrip("/")
        if href.startswith("/"):
            root = re.match(r"(https?://[^/]+)", base)
            return (root.group(1) if root else base) + href
        if href.startswith("?"):
            return base.split("?")[0] + href
        return base.rstrip("/") + "/" + href.lstrip("./")

    def type_text(self, node_id: int, text: str, force: bool = False) -> ActionResult:
        t0 = time.time()
        node = self.index().by_index(node_id)
        if node is None:
            return self._record("type", str(node_id), "", False, "element not found", t0)
        if node.tag not in ("input", "textarea", "select") and node.derived_role not in (
            "textbox", "searchbox", "combobox", "spinbutton",
        ):
            return self._record("type", node.accessible_name, "", False, "not an input", t0)
        if node.is_disabled:
            return self._record("type", node.accessible_name, "", False, "element disabled", t0)
        blocked = "" if force else self.guard.check(node)
        if blocked:
            return self._record("type", node.accessible_name, SensitiveDataGuard.redact(text),
                                False, blocked, t0)
        self.scroll_into_view(node)
        node.attributes["value"] = text
        return self._record("type", node.accessible_name, SensitiveDataGuard.redact(text),
                            True, f"{len(text)} chars", t0)

    def press(self, key: str) -> ActionResult:
        t0 = time.time()
        if key.lower() in ("enter", "return"):
            form = self._first_form()
            if form is not None:
                action = form.attributes.get("action", "")
                if action and self.site.get(self._resolve_url(action)):
                    return self.open(self._resolve_url(action))
                return self._record("press", key, "", True, "form submitted (no navigation)", t0)
            return self._record("press", key, "", True, "key pressed", t0)
        return self._record("press", key, "", True, "key pressed", t0)

    def _first_form(self) -> BrowserNode | None:
        root = self.tab.root
        if root is None:
            return None
        for node in root.walk():
            if node.tag == "form":
                return node
        return None

    # ── observation ───────────────────────────────────────────────────

    def state(self) -> PageState:
        tab = self.tab
        return PageState(
            url=tab.url,
            title=tab.title,
            root=tab.root,
            viewport=BoundingBox(0, 0, *self.viewport_size),
            scroll_y=tab.scroll_y,
            doc_height=tab.doc_height,
            tab_id=tab.tab_id,
            tabs=list(self.tabs),
        )

    def describe(self) -> str:
        return self.serializer.serialize(self.state())

    def _record(
        self, action: str, target: str, payload: str, ok: bool,
        detail: str, t0: float, url: str = "",
    ) -> ActionResult:
        self._seq += 1
        res = ActionResult(
            ok=ok, action=action, detail=detail, url=url or self.tab.url,
            node_id=int(target) if target.isdigit() else None,
            blocked="" if ok else detail,
            elapsed_ms=(time.time() - t0) * 1000.0,
        )
        self.actions.append(ActionRecord(
            seq=self._seq, action=action, target=target,
            payload=payload, url_before=self.tab.url, url_after=res.url, ok=ok,
        ))
        return res


# ── Form filling ──────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,20}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass
class FieldMatch:
    """Mapping between a requested key and a concrete input node."""

    key: str
    node_id: int
    label: str
    confidence: float
    input_type: str


@dataclass
class FormFillResult:
    """Outcome of filling a form."""

    filled: list[FieldMatch] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalid: dict[str, str] = field(default_factory=dict)
    blocked: dict[str, str] = field(default_factory=dict)
    ready_to_submit: bool = False
    errors: list[ActionResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.filled) and not self.invalid and not self.blocked and not self.missing


class FormFiller:
    """Fill a form from a mapping of human keys to values."""

    def __init__(self, session: BrowserSession) -> None:
        self.session = session

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

    def match(self, key: str, nodes: list[BrowserNode]) -> FieldMatch | None:
        needle = self._normalize(key)
        best: FieldMatch | None = None
        for node in nodes:
            if not node.is_interactive or node.action_kind not in ("input", "select"):
                continue
            haystacks = {
                "name": self._normalize(node.attributes.get("name", "")),
                "id": self._normalize(node.attributes.get("id", "")),
                "label": self._normalize(node.accessible_name),
                "placeholder": self._normalize(node.attributes.get("placeholder", "")),
            }
            confidence = 0.0
            for weight_key, weight in (("name", 0.95), ("id", 0.9), ("label", 0.85), ("placeholder", 0.7)):
                hay = haystacks[weight_key]
                if not hay:
                    continue
                if hay == needle:
                    confidence = max(confidence, weight)
                elif needle and (needle in hay or hay in needle):
                    overlap = min(len(hay), len(needle)) / max(len(hay), len(needle))
                    confidence = max(confidence, weight * 0.6 * overlap + 0.2)
            if confidence <= 0:
                continue
            if best is None or confidence > best.confidence:
                best = FieldMatch(
                    key=key, node_id=node.node_id, label=node.accessible_name,
                    confidence=round(confidence, 3), input_type=node.input_type or node.tag,
                )
        return best

    @staticmethod
    def validate(node: BrowserNode, value: str) -> str:
        """Return '' when valid, else a human-readable error."""
        itype = node.input_type
        if itype == "email" and not EMAIL_RE.match(value):
            return "invalid email"
        if itype == "tel" and not PHONE_RE.match(value):
            return "invalid phone number"
        if itype == "date" and not DATE_RE.match(value):
            return "date must be YYYY-MM-DD"
        if itype in ("number", "range") and not NUMBER_RE.match(value):
            return "not a number"
        if itype == "url" and not re.match(r"^https?://", value):
            return "url must start with http(s)://"
        maxlen = node.attributes.get("maxlength", "")
        if maxlen.isdigit() and len(value) > int(maxlen):
            return f"exceeds maxlength {maxlen}"
        return ""

    def fill(self, values: dict[str, str], scope_id: int | None = None) -> FormFillResult:
        idx = self.session.index()
        nodes = idx.all()
        if scope_id is not None:
            root = idx.by_index(scope_id)
            nodes = list(root.walk()) if root is not None else nodes
        result = FormFillResult()
        for key, value in values.items():
            match = self.match(key, nodes)
            if match is None:
                result.missing.append(key)
                continue
            node = idx.by_index(match.node_id)
            if node is None:
                result.missing.append(key)
                continue
            error = self.validate(node, value)
            if error:
                result.invalid[key] = error
                continue
            res = self.session.type_text(match.node_id, value)
            if not res.ok:
                result.blocked[key] = res.detail
                result.errors.append(res)
                continue
            result.filled.append(match)
        required_left = [
            n for n in nodes
            if n.is_interactive and "required" in n.attributes
            and not n.attributes.get("value", "")
        ]
        result.ready_to_submit = not required_left and not result.invalid and not result.missing
        return result


# ── Structured extraction ─────────────────────────────────────────────────

@dataclass
class FieldSelector:
    """How to pull one field out of the tree."""

    name: str
    tag: str = ""
    role: str = ""
    attribute: str = ""
    pattern: str = ""
    cast: str = "str"       # str | int | float | bool
    nth: int = 0
    required: bool = False


class DataExtractor:
    """Extract structured records from a page tree with typed casting."""

    def __init__(self, session: BrowserSession) -> None:
        self.session = session

    @staticmethod
    def _cast(value: str, kind: str) -> Any:
        cleaned = _norm_ws(value).replace(",", "").replace("$", "")
        try:
            if kind == "int":
                return int(float(cleaned))
            if kind == "float":
                return float(cleaned)
            if kind == "bool":
                return cleaned.lower() in ("true", "yes", "1", "on", "checked")
        except (TypeError, ValueError):
            return None
        return _norm_ws(value)

    def _value_for(self, nodes: list[BrowserNode], sel: FieldSelector) -> Any:
        candidates = nodes
        if sel.tag:
            candidates = [n for n in candidates if n.tag == sel.tag]
        if sel.role:
            candidates = [n for n in candidates if n.derived_role == sel.role]
        if not candidates:
            return None
        node = candidates[min(sel.nth, len(candidates) - 1)]
        raw = node.attributes.get(sel.attribute, "") if sel.attribute else node.text
        if not raw:
            raw = node.accessible_name
        if sel.pattern:
            match = re.search(sel.pattern, raw)
            if match is None:
                return None
            raw = match.group(1) if match.groups() else match.group(0)
        return self._cast(raw, sel.cast)

    def extract(self, selectors: list[FieldSelector], container_tag: str = "") -> list[dict[str, Any]]:
        """Extract one record per container node."""
        idx = self.session.index()
        containers = [n for n in idx.all() if n.tag == container_tag] if container_tag else []
        if not containers:
            containers = [self.session.tab.root] if self.session.tab.root else []
        records: list[dict[str, Any]] = []
        for container in containers:
            nodes = list(container.walk())
            record: dict[str, Any] = {}
            complete = True
            for sel in selectors:
                value = self._value_for(nodes, sel)
                if value is None and sel.required:
                    complete = False
                record[sel.name] = value
            if record and (complete or not any(s.required for s in selectors)):
                records.append(record)
        return records

    def extract_table(self) -> list[dict[str, str]]:
        """Read the first HTML-ish table into dict rows using its header cells."""
        idx = self.session.index()
        roots = idx.by_tag.get("table", [])
        if not roots:
            return []
        table = roots[0]
        rows = [n for n in table.walk() if n.tag == "tr"]
        if not rows:
            return []
        headers = [c.text or c.accessible_name for c in rows[0].children if c.tag in ("th", "td")]
        out: list[dict[str, str]] = []
        for row in rows[1:]:
            cells = [c.text or c.accessible_name for c in row.children if c.tag in ("td", "th")]
            if not cells:
                continue
            record = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) and headers[i] else f"col_{i}"
                record[key] = cell
            out.append(record)
        return out


# ── Goal-directed agent ───────────────────────────────────────────────────

STOPWORDS = {
    "the", "a", "an", "to", "and", "of", "in", "on", "for", "with", "please",
    "click", "go", "open", "find", "then", "my", "me", "it", "this", "that",
}

TYPE_INTENT_WORDS = {"search", "enter", "type", "fill", "input", "write", "set", "choose", "query"}
NAV_INTENT_WORDS = {"open", "go", "navigate", "visit", "click", "select", "view", "book"}


@dataclass
class AgentStep:
    """One step of a browser workflow run."""

    step: int
    url: str
    action: str
    target: str
    node_id: int | None
    ok: bool
    detail: str


@dataclass
class BrowserRun:
    """Result of a goal-directed run."""

    goal: str
    steps: list[AgentStep] = field(default_factory=list)
    success: bool = False
    final_url: str = ""
    reason: str = ""
    extracted: list[dict[str, Any]] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        return len(self.steps)


def tokenize(text: str) -> list[str]:
    return [
        t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
        if t and t not in STOPWORDS
    ]


class BrowserAgent:
    """Run a natural-language goal against a site graph.

    The loop is deterministic: score visible interactive elements against the
    goal tokens, prefer text entry when the goal asks for input, click the
    best match, follow a "next" affordance when nothing matches, and stop on
    success, exhaustion or a repeated action signature.
    """

    def __init__(
        self,
        session: BrowserSession | None = None,
        site: dict[str, SitePage] | None = None,
        goal_tokens: Iterable[str] | None = None,
    ) -> None:
        self.site = site or {}
        self.session = session or BrowserSession(self.site)
        self.serializer = DomSerializer()
        self.goal_tokens = set(goal_tokens or ())
        self.extractor = DataExtractor(self.session)

    def _score(self, node: BrowserNode, tokens: set[str], wants_input: bool) -> float:
        label_tokens = set(tokenize(f"{node.accessible_name} {node.attributes.get('placeholder', '')}"))
        overlap = len(label_tokens & tokens)
        if overlap == 0:
            return 0.0
        score = overlap / max(1, len(tokens)) * 4.0
        kind = node.action_kind
        if wants_input and kind in ("input", "select"):
            score += 1.5
        elif not wants_input and kind in ("click", "link", "submit"):
            score += 1.0
        if node.bounds is not None:
            score += 0.4 * node.bounds.visible_ratio(self.session.state().viewport_at_scroll())
        return round(score, 4)

    def _next_affordance(self, nodes: list[BrowserNode]) -> BrowserNode | None:
        for node in nodes:
            label = node.accessible_name.lower()
            if node.is_interactive and label in ("next", "continue", "next page", "more", "→", ">"):
                return node
        return None

    def run(
        self,
        goal: str,
        start_url: str = "",
        max_steps: int = 10,
        extract: list[FieldSelector] | None = None,
    ) -> BrowserRun:
        tokens = set(tokenize(goal))
        wants_input = bool(tokens & TYPE_INTENT_WORDS) or "search" in tokens
        self.session.site = self.session.site or self.site
        if start_url:
            self.session.open(start_url)
        elif not self.session.tab.url and self.site:
            self.session.open(next(iter(self.site)))

        run = BrowserRun(goal=goal)
        seen: set[tuple[str, str, int | None]] = set()

        for step in range(1, max_steps + 1):
            state = self.session.state()
            idx = SelectorIndex(state.root)
            nodes = [n for n in idx.all() if n.is_interactive]
            scored = sorted(
                ((self._score(n, tokens, wants_input), n) for n in nodes),
                key=lambda pair: pair[0], reverse=True,
            )
            best_score, best_node = (scored[0] if scored else (0.0, None))

            if best_node is None or best_score < 1.0:
                nxt = self._next_affordance(nodes)
                if nxt is None:
                    run.reason = "no actionable match on page"
                    break
                res = self.session.click(nxt.node_id)
                run.steps.append(AgentStep(
                    step, state.url, "click", nxt.accessible_name, nxt.node_id,
                    res.ok, res.detail,
                ))
                continue

            signature = (state.url, best_node.action_kind, best_node.node_id)
            if signature in seen:
                run.reason = "repeated action detected (loop guard)"
                break
            seen.add(signature)

            if best_node.action_kind in ("input", "select") and wants_input:
                query = " ".join(t for t in tokens if t not in TYPE_INTENT_WORDS)
                res = self.session.type_text(best_node.node_id, query or goal)
                run.steps.append(AgentStep(
                    step, state.url, "type", best_node.accessible_name,
                    best_node.node_id, res.ok, res.detail,
                ))
                submit = self._submit_for(best_node, nodes)
                if submit is not None:
                    res2 = self.session.click(submit.node_id)
                    run.steps.append(AgentStep(
                        step, state.url, "click", submit.accessible_name,
                        submit.node_id, res2.ok, res2.detail,
                    ))
            else:
                res = self.session.click(best_node.node_id)
                run.steps.append(AgentStep(
                    step, state.url, "click", best_node.accessible_name,
                    best_node.node_id, res.ok, res.detail,
                ))

            if not res.ok:
                run.reason = res.detail
                break
            if self._goal_satisfied(goal, tokens, self.session.state(), start_url):
                run.success = True
                run.reason = "goal reached"
                break
            if extract:
                run.extracted.extend(self.extractor.extract(extract))

        run.final_url = self.session.state().url
        if extract and not run.extracted:
            run.extracted = self.extractor.extract(extract)
        if not run.steps:
            run.reason = run.reason or "no steps executed"
        return run

    def _submit_for(self, field: BrowserNode, nodes: list[BrowserNode]) -> BrowserNode | None:
        for node in nodes:
            if node.action_kind == "submit":
                return node
        for node in nodes:
            if node.action_kind == "click" and node.tag == "button":
                label = node.accessible_name.lower()
                if any(word in label for word in ("search", "find", "submit", "go", "continue")):
                    return node
        return None

    def _goal_satisfied(
        self, goal: str, tokens: set[str], state: PageState, start_url: str = "",
    ) -> bool:
        """A goal counts as reached when the visible page carries its content words."""
        if state.root is None:
            return False
        content_tokens = tokens - TYPE_INTENT_WORDS - NAV_INTENT_WORDS
        scored_tokens = content_tokens or tokens
        if not scored_tokens:
            return False
        hay = " ".join([state.title, state.url] + [n.text for n in state.root.walk() if n.text]).lower()
        hay_tokens = set(tokenize(hay))
        coverage = len(scored_tokens & hay_tokens) / len(scored_tokens)
        confirmation = any(
            word in hay for word in ("success", "confirmed", "thank you", "complete", "added to cart")
        )
        navigated = state.url != start_url
        return coverage >= 0.6 and (confirmation or navigated)


# ── Recorder / replay ─────────────────────────────────────────────────────

class SessionRecorder:
    """Record a session's actions and verify deterministic replay."""

    def __init__(self, session: BrowserSession) -> None:
        self.session = session

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "seq": a.seq, "action": a.action, "target": a.target,
                "url_before": a.url_before, "url_after": a.url_after, "ok": a.ok,
            }
            for a in self.session.actions
        ]

    def replay(self, site: dict[str, SitePage], start_url: str) -> dict[str, Any]:
        """Re-execute the recorded log on a fresh session and compare outcomes."""
        fresh = BrowserSession(site)
        fresh.open(start_url)
        mismatches: list[str] = []
        executed = 0
        for record in self.snapshot():
            action = record["action"]
            target = record["target"]
            if action == "open":
                result = fresh.open(record["url_after"])
            elif action == "click" and target.isdigit():
                result = fresh.click(int(target))
            elif action == "type" and target.isdigit():
                result = fresh.type_text(int(target), "replayed")
            elif action == "scroll":
                result = fresh.scroll(200)
            elif action == "back":
                result = fresh.back()
            else:
                continue
            executed += 1
            if result.ok != record["ok"]:
                mismatches.append(f"seq {record['seq']}: ok {result.ok} != {record['ok']}")
        return {
            "executed": executed,
            "mismatches": mismatches,
            "deterministic": not mismatches,
            "final_url": fresh.state().url,
        }


# ── Module-level engine ───────────────────────────────────────────────────

class BrowserAutomationEngine:
    """High-level facade used by FRIDAY pipelines."""

    def __init__(self) -> None:
        self.serializer = DomSerializer()

    def build_site(self, pages: list[SitePage]) -> dict[str, SitePage]:
        return {page.url: page for page in pages}

    def inspect(self, page: SitePage, viewport: tuple[float, float] = (1280, 720)) -> dict[str, Any]:
        session = BrowserSession({page.url: page}, viewport=viewport)
        session.open(page.url)
        idx = session.index()
        interactive = idx.interactive()
        return {
            "url": page.url,
            "title": page.title,
            "interactive_elements": len(interactive),
            "inputs": len([n for n in interactive if n.action_kind in ("input", "select")]),
            "links": len([n for n in interactive if n.action_kind == "link"]),
            "serialized": session.describe(),
            "token_estimate": self.serializer.token_estimate(session.describe()),
        }

    def run_goal(self, pages: list[SitePage], goal: str, start_url: str = "", max_steps: int = 10) -> dict[str, Any]:
        site = self.build_site(pages)
        agent = BrowserAgent(site=site)
        run = agent.run(goal, start_url=start_url or (pages[0].url if pages else ""), max_steps=max_steps)
        return {
            "goal": run.goal,
            "success": run.success,
            "reason": run.reason,
            "final_url": run.final_url,
            "steps": [
                {"step": s.step, "action": s.action, "target": s.target, "ok": s.ok}
                for s in run.steps
            ],
        }


# Module-level instance
engine = BrowserAutomationEngine()
