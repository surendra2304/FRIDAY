"""Evidence-bound business workflows adapted from the Drive playbooks.

All operations are read-only over caller-supplied snapshots. Drafts and
recommendations are never sent, published, or written back to source systems.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from threading import Event, Thread


IDEA_SOURCE = {
    "drive_file_id": "1XcmTc8jVdlPPwXVK5XX0povCpTtrQ0qz",
    "title": "Ayman_William_200_AI_Business_Ideas_Editable.docx",
    "folder_id": "16-w2LiHKi1WZxRmvInuVSY3gMU5fHU8j",
    "principles": [
        "Start with a repeated buyer problem and measurable outcome.",
        "Test with five buyer conversations and a fixed-scope human-reviewed pilot before automating.",
        "Treat India-first costs and pricing as hypotheses; verify current tool prices and willingness to pay.",
        "Track retention, gross margin, review time, rework, acquisition and cost per successful task.",
        "Minimize customer data and require qualified human review for consequential domains.",
    ],
    "categories": [
        "AI Content & Creator Operations", "Marketing Intelligence & Growth", "AI Sales & Revenue Operations",
        "Voice, Customer Experience & Service Automation", "AI Agents & Workflow Automation",
        "Local Business AI Operating Systems", "Ecommerce & Retail Intelligence", "Education, Training & Career",
        "HR & Talent Operations", "Finance, Accounting & Commercial Operations", "Legal Operations, Risk & Compliance",
        "Healthcare & Wellness Operations", "Real Estate, Construction & Facilities",
        "Manufacturing, Supply Chain & Procurement", "Hospitality, Food & Travel", "Agriculture, Climate & Energy",
        "Cybersecurity & IT Operations", "Research, Knowledge & Workplace Intelligence",
        "India-First Language & Accessibility", "Generative Products & Vertical Micro-SaaS",
    ],
}

GROK_WORKFLOWS = {
    "lead_review": {"title": "Lead follow-up review", "mode": "read_only_drafts",
        "approval": "Do not message or update CRM records; human approval required.",
        "required_sources": ["lead records"], "output": ["classification", "reason", "draft", "next action", "source ID"]},
    "daily_ad_report": {"title": "Daily paid-media pulse", "mode": "read_only_report",
        "approval": "Do not change campaigns/budgets or send this report externally.",
        "required_sources": ["campaign metrics", "reporting window", "timezone", "attribution definition"],
        "output": ["summary", "campaign table", "flags", "source links", "freshness"]},
    "weekly_ops_sweep": {"title": "Weekly operations sweep", "mode": "read_only_report",
        "approval": "Do not edit tasks, contact customers, assign work, pause campaigns or delete data.",
        "required_sources": ["tasks", "leads", "campaigns"],
        "output": ["overdue commitments", "stalled leads", "campaign flags", "missing data", "three priorities"]},
}


@dataclass(frozen=True)
class WorkflowRun:
    workflow: str
    status: str
    generated_at: str
    output: dict[str, Any]
    assumptions: list[str]
    external_actions_taken: tuple[str, ...] = ()


_ORACLE_PREFIXES = ("oracle://", "oracle+oracledb://", "oracledb://")
_BUSINESS_DSN_ENV = (
    "FRIDAY_DATABASE_URL",
    "DATABASE_URL",
    "FRIDAY_UNIVERSE_DB_URL",
    "ORACLE_CORE_ASYNC_URL",
)


def _oracle_dsn(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text.lower().startswith(_ORACLE_PREFIXES):
        return None
    scheme, _, rest = text.partition("://")
    if scheme.lower() in {"oracle", "oracledb"}:
        return "oracle+oracledb://" + rest
    return text


def _resolve_business_dsn(state_dir: str | None) -> str | None:
    """Resolve the business-ops backend.

    An explicit Oracle DSN wins. Under pytest an explicit directory is a
    test-only SQLite override. Otherwise the FRIDAY Oracle DSN is resolved from
    the environment; a plain directory outside tests is refused in production.
    """
    explicit = _oracle_dsn(state_dir)
    if explicit:
        return explicit
    testing = "pytest" in sys.modules or (os.getenv("FRIDAY_ENV") or "").strip().lower() in {"testing", "test"}
    if state_dir and testing:
        return None
    configured_raw = next(
        ((os.getenv(key) or "").strip() for key in _BUSINESS_DSN_ENV if (os.getenv(key) or "").strip()),
        "",
    )
    configured = _oracle_dsn(configured_raw)
    if configured:
        return configured
    if state_dir:
        environment = (os.getenv("FRIDAY_ENV") or "").strip().lower()
        if environment == "production":
            raise RuntimeError(
                "FRIDAY business operations require an Oracle DSN in production; "
                "explicit directories are test-only."
            )
        return None
    if configured_raw:
        raise RuntimeError(
            "FRIDAY_DATABASE_URL must be an oracle+oracledb:// DSN; SQLite and "
            "PostgreSQL are not supported production backends."
        )
    raise RuntimeError(
        "FRIDAY business operations require an Oracle Autonomous Database DSN "
        "(FRIDAY_DATABASE_URL or DATABASE_URL)."
    )


def _lob_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    read = getattr(value, "read", None)
    return read() if callable(read) else str(value)


class _OracleBusinessStore:
    """Oracle-backed ideas, skills, routines, runs and snapshots."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._engine: Any | None = None
        self._lock = threading.RLock()
        self._ensure_schema()

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is None:
                from sqlalchemy import create_engine

                self._engine = create_engine(
                    self.dsn,
                    pool_pre_ping=True,
                    pool_size=3,
                    max_overflow=5,
                    pool_recycle=1800,
                )
        return self._engine

    def _ensure_schema(self) -> None:
        from sqlalchemy import text

        ddl = {
            "BUSINESS_IDEAS": """CREATE TABLE business_ideas (
                id VARCHAR2(10) PRIMARY KEY, category VARCHAR2(300), title VARCHAR2(500),
                buyer VARCHAR2(500), problem CLOB, solution CLOB, body CLOB,
                source_file VARCHAR2(300), imported_at VARCHAR2(80))""",
            "BUSINESS_SKILLS": """CREATE TABLE business_skills (
                id VARCHAR2(64) PRIMARY KEY, name VARCHAR2(100) UNIQUE, workflow VARCHAR2(100),
                spec CLOB, created_at VARCHAR2(80))""",
            "BUSINESS_ROUTINES": """CREATE TABLE business_routines (
                id VARCHAR2(64) PRIMARY KEY, skill_id VARCHAR2(64), weekdays VARCHAR2(64),
                local_time VARCHAR2(20), timezone VARCHAR2(100), enabled NUMBER(1),
                last_run VARCHAR2(80), created_at VARCHAR2(80), max_age_hours NUMBER)""",
            "BUSINESS_RUNS": """CREATE TABLE business_runs (
                id VARCHAR2(64) PRIMARY KEY, routine_id VARCHAR2(64), workflow VARCHAR2(100),
                status VARCHAR2(64), generated_at VARCHAR2(80), output CLOB)""",
            "BUSINESS_SNAPSHOTS": """CREATE TABLE business_snapshots (
                source_id VARCHAR2(100) NOT NULL, observed_at VARCHAR2(80) NOT NULL,
                payload CLOB NOT NULL, source_link VARCHAR2(1000),
                PRIMARY KEY (source_id, observed_at))""",
        }
        with self._get_engine().begin() as conn:
            for table, statement in ddl.items():
                present = conn.execute(
                    text("SELECT COUNT(*) FROM user_tables WHERE table_name = :name"),
                    {"name": table},
                ).scalar_one()
                if not present:
                    conn.exec_driver_sql(statement)

    def import_ideas(self, cards: list[dict], imported_at: str) -> None:
        from sqlalchemy import text

        statement = text(
            """MERGE INTO business_ideas target
               USING (SELECT :id AS id FROM dual) source
               ON (target.id = source.id)
               WHEN MATCHED THEN UPDATE SET category = :category, title = :title,
                   buyer = :buyer, problem = :problem, solution = :solution, body = :body,
                   source_file = :source_file, imported_at = :imported_at
               WHEN NOT MATCHED THEN INSERT
                   (id, category, title, buyer, problem, solution, body, source_file, imported_at)
                   VALUES (:id, :category, :title, :buyer, :problem, :solution, :body,
                           :source_file, :imported_at)"""
        )
        with self._get_engine().begin() as conn:
            for card in cards:
                conn.execute(statement, {**card, "imported_at": imported_at})

    def list_ideas(self) -> list[dict]:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            rows = conn.execute(
                text("""SELECT id, category, title, buyer, problem, solution, body, source_file
                        FROM business_ideas""")
            ).fetchall()
        keys = ("id", "category", "title", "buyer", "problem", "solution", "body", "source_file")
        return [
            {key: (_lob_text(value) if key in {"problem", "solution", "body"} else value)
             for key, value in zip(keys, row)}
            for row in rows
        ]

    def save_skill(self, skill_id: str, name: str, workflow: str, spec: str, created_at: str) -> None:
        from sqlalchemy import text

        statement = text(
            """MERGE INTO business_skills target
               USING (SELECT :name AS name FROM dual) source
               ON (target.name = source.name)
               WHEN MATCHED THEN UPDATE SET id = :id, workflow = :workflow,
                   spec = :spec, created_at = :created_at
               WHEN NOT MATCHED THEN INSERT (id, name, workflow, spec, created_at)
                   VALUES (:id, :name, :workflow, :spec, :created_at)"""
        )
        with self._get_engine().begin() as conn:
            conn.execute(statement, {"id": skill_id, "name": name, "workflow": workflow,
                                     "spec": spec, "created_at": created_at})

    def list_skills(self) -> list[dict]:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            rows = conn.execute(
                text("""SELECT id, name, workflow, spec, created_at FROM business_skills
                        ORDER BY created_at DESC""")
            ).fetchall()
        return [{"skill_id": row[0], "name": row[1], "workflow": row[2],
                 "spec": json.loads(_lob_text(row[3])), "created_at": row[4]} for row in rows]

    def skill_exists(self, skill_id: str) -> bool:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM business_skills WHERE id = :id"), {"id": skill_id}
            ).scalar_one()
        return bool(count)

    def insert_routine(self, routine_id: str, skill_id: str, weekdays: str, local_time: str,
                       timezone_name: str, created: str, max_age_hours: float) -> None:
        from sqlalchemy import text

        with self._get_engine().begin() as conn:
            conn.execute(
                text("""INSERT INTO business_routines
                        (id, skill_id, weekdays, local_time, timezone, enabled, last_run,
                         created_at, max_age_hours)
                        VALUES (:id, :skill_id, :weekdays, :local_time, :timezone, 1, NULL,
                                :created_at, :max_age_hours)"""),
                {"id": routine_id, "skill_id": skill_id, "weekdays": weekdays,
                 "local_time": local_time, "timezone": timezone_name,
                 "created_at": created, "max_age_hours": max_age_hours},
            )

    def get_routine(self, routine_id: str) -> dict | None:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            row = conn.execute(
                text("""SELECT weekdays, local_time, timezone, enabled, last_run, max_age_hours,
                               skill_id FROM business_routines WHERE id = :id"""),
                {"id": routine_id},
            ).fetchone()
        if row is None:
            return None
        keys = ("weekdays", "local_time", "timezone", "enabled", "last_run", "max_age_hours", "skill_id")
        return dict(zip(keys, row))

    def list_routines(self) -> list[dict]:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            rows = conn.execute(
                text("""SELECT id, skill_id, weekdays, local_time, timezone, enabled, last_run,
                               max_age_hours FROM business_routines ORDER BY created_at DESC""")
            ).fetchall()
        return [{"routine_id": r[0], "skill_id": r[1], "weekdays": json.loads(r[2]),
                 "local_time": r[3], "timezone": r[4], "enabled": bool(r[5]),
                 "last_run": r[6], "max_snapshot_age_hours": r[7]} for r in rows]

    def routine_skill(self, routine_id: str) -> dict | None:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            row = conn.execute(
                text("""SELECT s.workflow, s.spec, r.enabled, r.max_age_hours
                        FROM business_routines r JOIN business_skills s ON s.id = r.skill_id
                        WHERE r.id = :id"""),
                {"id": routine_id},
            ).fetchone()
        if row is None:
            return None
        return {"workflow": row[0], "spec": _lob_text(row[1]),
                "enabled": bool(row[2]), "max_age_hours": row[3]}

    def ingest_snapshot(self, source_id: str, observed_at: str, body: str,
                        source_link: str | None) -> None:
        from sqlalchemy import text

        merge = text(
            """MERGE INTO business_snapshots target
               USING (SELECT :source_id AS source_id, :observed_at AS observed_at FROM dual) source
               ON (target.source_id = source.source_id AND target.observed_at = source.observed_at)
               WHEN MATCHED THEN UPDATE SET payload = :payload, source_link = :source_link
               WHEN NOT MATCHED THEN INSERT (source_id, observed_at, payload, source_link)
                   VALUES (:source_id, :observed_at, :payload, :source_link)"""
        )
        prune = text(
            """DELETE FROM business_snapshots
               WHERE source_id = :source_id
                 AND observed_at < (
                     SELECT MIN(observed_at) FROM (
                         SELECT observed_at FROM business_snapshots
                         WHERE source_id = :source_id ORDER BY observed_at DESC
                     ) WHERE ROWNUM <= 10)"""
        )
        params = {"source_id": source_id, "observed_at": observed_at,
                  "payload": body, "source_link": source_link}
        with self._get_engine().begin() as conn:
            conn.execute(merge, params)
            conn.execute(prune, {"source_id": source_id})

    def snapshot_rows(self, source_id: str) -> list[dict]:
        from sqlalchemy import text

        with self._get_engine().connect() as conn:
            rows = conn.execute(
                text("""SELECT observed_at, payload, source_link FROM business_snapshots
                        WHERE source_id = :source_id ORDER BY observed_at DESC
                        FETCH FIRST 10 ROWS ONLY"""),
                {"source_id": source_id},
            ).fetchall()
        return [{"observed_at": row[0], "payload": _lob_text(row[1]), "source_link": row[2]}
                for row in rows]

    def insert_run(self, run_id: str, routine_id: str, workflow: str, status: str,
                   generated_at: str, output: str) -> None:
        from sqlalchemy import text

        with self._get_engine().begin() as conn:
            conn.execute(
                text("""INSERT INTO business_runs
                        (id, routine_id, workflow, status, generated_at, output)
                        VALUES (:id, :routine_id, :workflow, :status, :generated_at, :output)"""),
                {"id": run_id, "routine_id": routine_id, "workflow": workflow,
                 "status": status, "generated_at": generated_at, "output": output},
            )

    def update_last_run(self, routine_id: str, generated_at: str) -> None:
        from sqlalchemy import text

        with self._get_engine().begin() as conn:
            conn.execute(
                text("UPDATE business_routines SET last_run = :last_run WHERE id = :id"),
                {"last_run": generated_at, "id": routine_id},
            )

    def set_enabled(self, routine_id: str, enabled: bool) -> int:
        from sqlalchemy import text

        with self._get_engine().begin() as conn:
            result = conn.execute(
                text("UPDATE business_routines SET enabled = :enabled WHERE id = :id"),
                {"enabled": 1 if enabled else 0, "id": routine_id},
            )
        return int(result.rowcount or 0)

    def claim_due_slot(self, routine_id: str, current: datetime, parse_date) -> tuple | None:
        """Lock one routine row, claim a due slot and persist ``last_run``."""
        from sqlalchemy import text

        with self._get_engine().begin() as conn:
            row = conn.execute(
                text("""SELECT weekdays, local_time, timezone, enabled, last_run, max_age_hours,
                               skill_id FROM business_routines WHERE id = :id FOR UPDATE"""),
                {"id": routine_id},
            ).fetchone()
            if row is None:
                raise KeyError(routine_id)
            weekdays, local_clock, zone_name, enabled, last_run, max_age, skill_id = row
            if not enabled:
                return None
            zone = ZoneInfo(zone_name)
            local_now = current.astimezone(zone)
            last = parse_date(last_run, "last_run", ZoneInfo("UTC")) if last_run else None
            target = time.fromisoformat(local_clock)
            slot = None
            for offset in range(8):
                day = (local_now - timedelta(days=offset)).date()
                candidate = datetime.combine(day, target, zone)
                if (day.weekday() in json.loads(weekdays) and candidate <= local_now
                        and (last is None or candidate > last.astimezone(zone))):
                    slot = candidate
                    break
            if slot is None:
                return None
            conn.execute(
                text("UPDATE business_routines SET last_run = :last_run WHERE id = :id"),
                {"last_run": slot.isoformat(), "id": routine_id},
            )
            return slot, max_age, skill_id


class BusinessOpsEngine:
    """Drive-sourced business design and Grok-style reviewed workflow routines."""

    def __init__(self, state_dir: str = "") -> None:
        dsn = _resolve_business_dsn(state_dir)
        self._oracle: _OracleBusinessStore | None = _OracleBusinessStore(dsn) if dsn else None
        self.database = dsn if self._oracle is not None else str(Path(state_dir) / "business_ops.sqlite3")
        if self._oracle is None:
            Path(state_dir).mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.database) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("""CREATE TABLE IF NOT EXISTS ideas (
                    id TEXT PRIMARY KEY, category TEXT, title TEXT, buyer TEXT, problem TEXT,
                    solution TEXT, body TEXT, source_file TEXT, imported_at TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE, workflow TEXT, spec TEXT, created_at TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY, skill_id TEXT, weekdays TEXT, local_time TEXT,
                    timezone TEXT, enabled INTEGER, last_run TEXT, created_at TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, routine_id TEXT, workflow TEXT, status TEXT,
                    generated_at TEXT, output TEXT)""")
                db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                    source_id TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
                    source_link TEXT, PRIMARY KEY(source_id, observed_at))""")
                routine_columns = {row[1] for row in db.execute("PRAGMA table_info(routines)")}
                if "max_age_hours" not in routine_columns:
                    db.execute("ALTER TABLE routines ADD COLUMN max_age_hours REAL NOT NULL DEFAULT 24")
        self._scheduler_stop: Event | None = None
        self._scheduler_thread: Thread | None = None

    @staticmethod
    def _clean(text: Any, maximum: int = 10000) -> str:
        if not isinstance(text, str) or len(text) > maximum:
            raise ValueError(f"text must be a string no longer than {maximum} characters")
        return " ".join(text.split())

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {t.casefold() for t in re.findall(r"[\w'-]+", text, flags=re.UNICODE) if len(t) > 2}

    def import_ideas(self, text: str, source_file: str = "Drive business ideas playbook") -> dict:
        """Import extracted DOCX text without assuming its 200 cards are complete."""
        if not isinstance(text, str) or not 100 <= len(text) <= 2_000_000:
            raise ValueError("idea text must contain 100 to 2,000,000 characters")
        source_file = self._clean(source_file, 300)
        if source_file not in {IDEA_SOURCE["title"], "Drive business ideas playbook"}:
            raise ValueError("only the inspected Drive business-ideas source can be imported here")
        markers = list(re.finditer(r"(?im)^[ \t]*IDEA\s+(\d{1,3})[ \t]*(?:\t| {2,})([^\n]*)", text))
        if not markers:
            raise ValueError("no numbered IDEA cards found")
        if len(markers) > 200:
            raise ValueError("more than 200 cards; refusing unexpected source structure")
        labels = ("PROBLEM STATEMENT", "SOLUTION STATEMENT", "HOW TO GET STARTED", "PROOF OF VALUE",
                  "REVENUE MODEL", "SELL THIS FIRST", "IDEAL FIRST BUYER", "FOUNDER INTERESTS",
                  "REQUIREMENTS", "TOOLKIT", "LEAN STARTUP BUDGET", "SCALE CEILING", "SCALE SPEED / FIRST PAID PILOT")
        parsed = []
        for index, marker in enumerate(markers):
            chunk = text[marker.start(): markers[index+1].start() if index+1 < len(markers) else len(text)]
            lines = [self._clean(line, 10000) for line in chunk.splitlines() if self._clean(line, 10000)]
            header = marker.group(2).strip()
            category = self._clean(header, 300)
            heading = lines[1] if len(lines) > 1 else f"Idea {marker.group(1)}"
            next_line = lines[2] if len(lines) > 2 else ""
            # Ignore repeated footer boilerplate that can appear between cards.
            if "AYMAN WILLIAM" in heading.upper(): heading = next_line or f"Idea {marker.group(1)}"
            fields: dict[str, str] = {}
            for label in labels:
                match = re.search(r"(?is)\b" + re.escape(label) + r"\b\s*(.*?)(?=\b(?:" +
                                  "|".join(map(re.escape, labels)) + r")\b|$)", chunk)
                if match:
                    fields[label] = self._clean(match.group(1), 10000)
            buyer = fields.get("IDEAL FIRST BUYER", next_line)[:500]
            problem = fields.get("PROBLEM STATEMENT", "")
            solution = fields.get("SOLUTION STATEMENT", "")
            title = self._clean(heading.replace("IDEA " + marker.group(1), ""), 500)
            if not title or title.upper().startswith("AYMAN WILLIAM"):
                title = f"Idea {int(marker.group(1)):03d}"
            parsed.append({"id": f"{int(marker.group(1)):03d}", "category": category[:300], "title": title,
                           "buyer": buyer, "problem": problem, "solution": solution,
                           "body": chunk[:20000], "source_file": source_file})
        now = datetime.now().astimezone().isoformat()
        if self._oracle is not None:
            self._oracle.import_ideas(parsed, now)
        else:
            with sqlite3.connect(self.database) as db:
                for card in parsed:
                    db.execute("INSERT OR REPLACE INTO ideas VALUES (?,?,?,?,?,?,?,?,?)",
                        (card["id"], card["category"], card["title"], card["buyer"], card["problem"],
                         card["solution"], card["body"], card["source_file"], now))
        return {"imported": len(parsed), "source_file": source_file,
                "source": {"file_id": IDEA_SOURCE["drive_file_id"], "folder_id": IDEA_SOURCE["folder_id"]},
                "partial_import_allowed": len(parsed) < 200}

    def recommend_ideas(self, query: str, limit: int = 10) -> dict:
        query = self._clean(query, 2000)
        if not query or not 1 <= limit <= 50:
            raise ValueError("query and a limit between 1 and 50 are required")
        terms = self._tokens(query)
        if self._oracle is not None:
            cards = self._oracle.list_ideas()
        else:
            with sqlite3.connect(self.database) as db:
                rows = db.execute("SELECT id,category,title,buyer,problem,solution,body,source_file FROM ideas").fetchall()
            cards = [dict(zip(("id", "category", "title", "buyer", "problem", "solution", "body", "source_file"), row))
                     for row in rows]
        if not cards:
            ranked_categories = sorted(((len(terms & self._tokens(category)), category)
                                        for category in IDEA_SOURCE["categories"]), key=lambda item:(-item[0],item[1]))
            matches = [{"category": category, "score": score,
                        "citation": {"drive_file_id": IDEA_SOURCE["drive_file_id"], "source_file": IDEA_SOURCE["title"]}}
                       for score,category in ranked_categories[:limit] if score]
            return {"status": "category_matches_only", "results": matches,
                    "catalog": IDEA_SOURCE,
                    "guidance": "Import extracted Drive card text via POST /api/business/ideas/import for exact 200-card recommendations."}
        ranked = []
        for card in cards:
            fields = {"title": self._tokens(card["title"]), "buyer": self._tokens(card["buyer"]),
                      "problem": self._tokens(card["problem"]), "solution": self._tokens(card["solution"]),
                      "category": self._tokens(card["category"])}
            score = (4*len(terms & fields["title"]) + 3*len(terms & fields["buyer"]) +
                     2*len(terms & fields["problem"]) + len(terms & fields["solution"]) +
                     len(terms & fields["category"]))
            if score:
                ranked.append((score, card))
        ranked.sort(key=lambda x: (-x[0], x[1]["id"]))
        return {"status": "ok", "query": query,
                "results": [{**card, "score": score,
                             "citation": {"drive_file_id": IDEA_SOURCE["drive_file_id"],
                                          "source_file": card["source_file"]}}
                            for score, card in ranked[:limit]],
                "catalog_count": len(cards), "heuristic": "token-overlap ranking, not market validation"}

    def score_idea(self, idea: dict[str, Any]) -> dict:
        """Transparent readiness checklist; scores are founder inputs, not predictions."""
        dimensions = ("buyer_access", "problem_frequency", "measurable_outcome", "permissioned_data",
                      "human_review", "repeatability", "unit_economics")
        scores = {}
        for name in dimensions:
            value = idea.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 5:
                raise ValueError(f"{name} must be a user-assessed score from 0 to 5")
            scores[name] = float(value)
        total = sum(scores.values())
        blockers = [name for name, value in scores.items() if value < 3]
        return {"score": total, "out_of": 35, "dimensions": scores, "blockers": blockers,
                "interpretation": "A planning checklist only; this is not a success probability or investment claim.",
                "next_14_days": ["Interview five reachable buyers.", "Agree one measurable KPI.",
                    "Run one fixed-scope, human-reviewed pilot.", "Measure rework, retention and cost per accepted result.",
                    "Ask for paid continuation; revise the problem if nobody will pay."],
                "safety": ["Use permissioned inputs.", "Minimize personal/customer data.",
                    "Require qualified review for healthcare, legal, hiring, finance or safety decisions."]}

    @staticmethod
    def _date(value: Any, field: str, timezone: ZoneInfo) -> datetime | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str) or len(value) > 80:
            raise ValueError(f"{field} must be an ISO date/time string")
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid {field}") from error
        return result.replace(tzinfo=timezone) if result.tzinfo is None else result.astimezone(timezone)

    @staticmethod
    def _number(value: Any, field: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{field} must be a finite nonnegative number")
        return float(value)

    def review_leads(self, leads: list[dict], as_of: str, stale_days: int = 5) -> dict:
        if not isinstance(leads,list) or len(leads)>5000 or not isinstance(stale_days,int) or isinstance(stale_days,bool) or not 0<=stale_days<=365:
            raise ValueError("lead list or stale-day limit invalid")
        timezone = ZoneInfo("UTC")
        now = self._date(as_of, "as_of", timezone)
        if now is None: raise ValueError("as_of is required")
        reviewed, excluded = [], 0
        contact_owner = {}
        duplicate_records = 0
        missing_records = 0
        for i, source in enumerate(leads):
            if not isinstance(source,dict): raise ValueError("each lead record must be an object")
            lead = dict(source)
            record_id = self._clean(str(lead.get("id", f"lead-{i+1}")), 200)
            optout_value = str(lead.get("contact_preference", "")).strip().casefold()
            if (lead.get("opted_out") is True or lead.get("do_not_contact") is True or
                    optout_value in {"opted_out", "do_not_contact", "do not contact", "unsubscribe"}):
                excluded += 1
                continue
            status = str(lead.get("status", "")).strip().casefold()
            added = self._date(lead.get("created_at"), "created_at", timezone)
            activity = self._date(lead.get("last_activity_at"), "last_activity_at", timezone)
            days_idle = (now-activity).days if activity else None
            if status in {"won", "closed won"}: classification = "Won"
            elif status in {"not a fit", "lost", "closed lost"}: classification = "Not a fit"
            elif status in {"waiting", "waiting on customer", "customer response"}: classification = "Waiting on customer"
            elif activity and days_idle is not None and days_idle >= stale_days: classification = "Needs follow-up"
            elif not activity and added and (now-added).days <= stale_days: classification = "New"
            elif not activity and added and (now-added).days > stale_days: classification = "Needs follow-up"
            elif not activity or not status: classification = "Unclear"
            else: classification = "Waiting on customer"
            name = self._clean(str(lead.get("name", "")), 200)
            interest = self._clean(str(lead.get("interest", "")), 500)
            missing_fields=[]
            for field_name in ("name", "created_at", "interest", "status", "owner", "last_activity_at"):
                if lead.get(field_name) in (None, ""):
                    missing_fields.append(field_name)
            contact = str(lead.get("email") or lead.get("contact") or "").strip().casefold()
            if not contact:
                missing_fields.append("contact")
            duplicate_of = contact_owner.get(contact) if contact else None
            if duplicate_of:
                duplicate_records += 1
            elif contact:
                contact_owner[contact]=record_id
            if missing_fields:
                missing_records += 1
            draft = ""
            if classification in {"New", "Needs follow-up"} and not duplicate_of:
                greeting = f"Hi {name}," if name else "Hello,"
                known = f"your interest in {interest}" if interest else "our recent conversation"
                last = f" Our last recorded interaction was {activity.date().isoformat()}." if activity else ""
                draft = f"{greeting} I'm following up on {known}.{last} Would it be useful to discuss next steps?"
            reviewed.append({"id": record_id, "name": name or None, "classification": classification,
                             "days_since_activity": days_idle, "missing_fields": missing_fields,
                             "duplicate_of": duplicate_of,
                             "reason": f"Source status: {status or 'not supplied'}; activity date: {activity.date().isoformat() if activity else 'not supplied'}.",
                             "draft": draft, "next_action": "Human review; send only after approval." if draft else "Review source record if status is unclear.",
                             "source_link": self._clean(str(lead.get("source_link", "")), 1000) or None})
        return {"as_of": now.isoformat(), "stale_days": stale_days, "records_reviewed": len(leads),
                "excluded_opt_out": excluded, "duplicate_records": duplicate_records,
                "records_with_missing_fields": missing_records, "classifications": reviewed,
                "message_sent": False, "records_changed": False,
                "note": "Drafts use only supplied name, interest and interaction date; no external message was sent."}

    def daily_ad_report(self, campaigns: list[dict], *, date_range: str, timezone_name: str,
                        attribution_window: str, thresholds: dict | None = None,
                        daily_budget: float | None = None, monthly_budget: float | None = None,
                        month_to_date_spend: float | None = None) -> dict:
        if not isinstance(campaigns,list) or len(campaigns)>1000:
            raise ValueError("campaign count must be a list of at most 1000 records")
        try: zone=ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError,TypeError) as error: raise ValueError("valid IANA timezone required") from error
        date_range=self._clean(date_range,100);attribution_window=self._clean(attribution_window,100)
        rules={"spend_change_pct":25.0,"cpl_rise_pct":20.0,"budget_over_pct":0.0,**(thresholds or {})}
        for key,value in rules.items():
            parsed=self._number(value,key)
            if parsed is None or parsed>10000:raise ValueError(f"invalid threshold {key}")
            rules[key]=parsed
        daily_budget=self._number(daily_budget,"daily_budget")
        monthly_budget=self._number(monthly_budget,"monthly_budget")
        month_to_date_spend=self._number(month_to_date_spend,"month_to_date_spend")
        rows=[];flags=[];missing=[];freshness=[]
        metric_names=("spend","impressions","clicks","leads","purchases","revenue")
        totals={key:0.0 for key in metric_names};available={key:True for key in metric_names}
        for index,campaign in enumerate(campaigns):
            if not isinstance(campaign,dict):raise ValueError("each campaign must be an object")
            cid=self._clean(str(campaign.get("id",f"campaign-{index+1}")),200)
            row={"id":cid,"name":self._clean(str(campaign.get("name", "")),200) or cid,
                 "source_link":self._clean(str(campaign.get("source_link","")),1000) or None}
            for metric in metric_names:
                value=self._number(campaign.get(metric),f"{cid}.{metric}")
                row[metric]=value
                if value is None:available[metric]=False;missing.append(f"{cid}.{metric}")
                else:totals[metric]+=value
            row["reach"]=self._number(campaign.get("reach"),f"{cid}.reach")
            row["ctr_pct"]=100*row["clicks"]/row["impressions"] if row["clicks"] is not None and row["impressions"] is not None and row["impressions"]>0 else None
            row["cpc"]=row["spend"]/row["clicks"] if row["spend"] is not None and row["clicks"] is not None and row["clicks"]>0 else None
            row["cpl"]=row["spend"]/row["leads"] if row["spend"] is not None and row["leads"] is not None and row["leads"]>0 else None
            row["cpa"]=row["spend"]/row["purchases"] if row["spend"] is not None and row["purchases"] is not None and row["purchases"]>0 else None
            row["roas"]=row["revenue"]/row["spend"] if row["revenue"] is not None and row["spend"] is not None and row["spend"]>0 else None
            budget=self._number(campaign.get("budget"),f"{cid}.budget")
            row["budget"]=budget
            row["budget_utilization_pct"]=100*row["spend"]/budget if row["spend"] is not None and budget and budget>0 else None
            if budget is not None and row["spend"] is not None and row["spend"]>budget*(1+rules["budget_over_pct"]/100):
                flags.append({"campaign_id":cid,"metric":"campaign_budget","spend":row["spend"],"budget":budget})
            updated=None
            if campaign.get("updated_at"):
                updated=self._date(campaign.get("updated_at"),f"{cid}.updated_at",zone)
            row["data_updated_at"]=updated.isoformat() if updated else None
            freshness.append({"campaign_id":cid,"updated_at":row["data_updated_at"],"source_link":row["source_link"]})
            if updated is None:missing.append(f"{cid}.updated_at")
            comparisons={}
            for period,key in (("previous_day","previous"),("seven_day_average","seven_day_average")):
                baseline=campaign.get(key,{}) or {}
                if not isinstance(baseline,dict):raise ValueError(f"{cid}.{key} must be an object")
                changes={}
                for metric in ("spend","cpl"):
                    current=row[metric] if metric=="spend" else row["cpl"]
                    old=self._number(baseline.get(metric),f"{cid}.{key}.{metric}")
                    change=(current-old)/old*100 if current is not None and old not in (None,0) else None
                    changes[metric]=change
                    if change is not None and metric=="spend" and abs(change)>rules["spend_change_pct"]:
                        flags.append({"campaign_id":cid,"metric":"spend","comparison":period,
                                      "change_pct":change,"rule_pct":rules["spend_change_pct"]})
                    if change is not None and metric=="cpl" and change>rules["cpl_rise_pct"]:
                        flags.append({"campaign_id":cid,"metric":"cpl","comparison":period,
                                      "change_pct":change,"rule_pct":rules["cpl_rise_pct"]})
                comparisons[period]=changes
            row["comparison_change_pct"]=comparisons
            rows.append(row)
        total={k:(v if available[k] else None) for k,v in totals.items()}
        total.update({"ctr_pct":100*totals["clicks"]/totals["impressions"] if available["clicks"] and available["impressions"] and totals["impressions"]>0 else None,
            "cpc":totals["spend"]/totals["clicks"] if available["spend"] and available["clicks"] and totals["clicks"]>0 else None,
            "cpl":totals["spend"]/totals["leads"] if available["spend"] and available["leads"] and totals["leads"]>0 else None,
            "cpa":totals["spend"]/totals["purchases"] if available["spend"] and available["purchases"] and totals["purchases"]>0 else None,
            "roas":totals["revenue"]/totals["spend"] if available["revenue"] and available["spend"] and totals["spend"]>0 else None,
            "reach":None,"reach_note":"Not summed: campaign reach can overlap without deduplication data."})
        if daily_budget is not None and total["spend"] is not None and total["spend"]>daily_budget*(1+rules["budget_over_pct"]/100):
            flags.append({"metric":"daily_budget","spend":total["spend"],"budget":daily_budget})
        if monthly_budget is not None and month_to_date_spend is not None and month_to_date_spend>monthly_budget:
            flags.append({"metric":"monthly_budget","month_to_date_spend":month_to_date_spend,"budget":monthly_budget})
        return {"date_range":date_range,"timezone":timezone_name,"attribution_window":attribution_window,
            "campaigns":rows,"account_total":total,"flags":flags,"investigation_suggestions":flags[:3],
            "missing_metrics":sorted(set(missing)),"daily_budget":daily_budget,"monthly_budget":monthly_budget,
            "month_to_date_spend":month_to_date_spend,
            "summary":"Verified arithmetic from supplied values only; missing metrics remain unavailable.",
            "thresholds":rules,"source_links":[r["source_link"] for r in rows if r["source_link"]],
            "data_freshness":{"status":"known" if any(x["updated_at"] for x in freshness) else "unknown","campaigns":freshness},
            "campaigns_changed":False,"report_sent":False}

    def weekly_ops_sweep(self, tasks: list[dict], leads: list[dict], campaigns: list[dict], *,
                         as_of: str, date_range: str, timezone_name: str,
                         attribution_window: str, failures: list[dict] | None = None) -> dict:
        try: tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError) as error: raise ValueError("valid IANA timezone required") from error
        now = self._date(as_of, "as_of", tz)
        if now is None: raise ValueError("as_of is required")
        if any(not isinstance(rows,list) for rows in (tasks,leads,campaigns)) or not isinstance(failures or [],list) or max(len(tasks),len(leads),len(campaigns),len(failures or []))>5000:
            raise ValueError("source snapshots must be lists of at most 5000 items")
        if any(not isinstance(item,dict) for item in tasks):raise ValueError("each task record must be an object")
        overdue = []
        for index, task in enumerate(tasks):
            due = self._date(task.get("due_at"), "task.due_at", tz)
            if due and due < now and str(task.get("status", "")).casefold() not in {"done", "completed", "cancelled"}:
                overdue.append({"id": self._clean(str(task.get("id", f"task-{index+1}")), 200),
                                "owner": self._clean(str(task.get("owner", "")), 200) or None,
                                "due_at": due.isoformat(), "source_link": self._clean(str(task.get("source_link", "")),1000) or None})
        lead_result = self.review_leads(leads, now.isoformat())
        stale_leads = [item for item in lead_result["classifications"] if item["classification"] == "Needs follow-up"]
        ad_result = self.daily_ad_report(campaigns, date_range=date_range, timezone_name=timezone_name,
                                         attribution_window=attribution_window)
        failures = failures or []
        priorities = []
        priorities.extend({"priority": "overdue_commitment", **task} for task in overdue)
        priorities.extend({"priority": "stalled_lead", "id": item["id"], "source_link": item["source_link"]} for item in stale_leads)
        priorities.extend({"priority": "campaign_threshold", **flag} for flag in ad_result["flags"])
        priorities.extend({"priority": "source_failure", "source": str(item.get("source", "unknown"))[:200],
                           "detail": str(item.get("detail", "unavailable"))[:500]} for item in failures[:100])
        return {"as_of": now.isoformat(), "overdue_commitments": overdue, "stalled_leads": stale_leads,
                "campaign_flags": ad_result["flags"], "missing_metrics": ad_result["missing_metrics"],
                "source_failures": failures[:100], "top_priorities": priorities[:3],
                "source_links": list(dict.fromkeys([x.get("source_link") for x in overdue+stale_leads if x.get("source_link")] + ad_result["source_links"])),
                "recommendations_are_drafts": True, "source_records_changed": False,
                "external_messages_sent": False}

    def run(self, workflow: str, data: dict[str, Any]) -> WorkflowRun:
        if workflow not in GROK_WORKFLOWS: raise ValueError("unknown built-in workflow")
        generated = datetime.now().astimezone().isoformat()
        if workflow == "lead_review":
            output = self.review_leads(data.get("leads", []), data.get("as_of", generated), int(data.get("stale_days", 5)))
        elif workflow == "daily_ad_report":
            output = self.daily_ad_report(data.get("campaigns", []), date_range=data.get("date_range", "unspecified"),
                    timezone_name=data.get("timezone", "UTC"), attribution_window=data.get("attribution_window", "unspecified"),
                    thresholds=data.get("thresholds"), daily_budget=data.get("daily_budget"),
                    monthly_budget=data.get("monthly_budget"), month_to_date_spend=data.get("month_to_date_spend"))
        else:
            output = self.weekly_ops_sweep(data.get("tasks", []), data.get("leads", []), data.get("campaigns", []),
                    as_of=data.get("as_of", generated), date_range=data.get("date_range", "unspecified"),
                    timezone_name=data.get("timezone", "UTC"), attribution_window=data.get("attribution_window", "unspecified"),
                    failures=data.get("failures"))
        return WorkflowRun(workflow, "completed", generated, output,
                           ["Caller-supplied snapshot only.", "No records were edited and no message was sent."])

    def create_skill(self, name: str, workflow: str, spec: dict[str, Any]) -> dict:
        name = self._clean(name, 100)
        if not name or workflow not in GROK_WORKFLOWS: raise ValueError("name and supported workflow required")
        required = {"purpose", "sources", "steps", "validation", "missing_data", "output_format", "approval_boundaries"}
        if set(spec) != required: raise ValueError(f"skill spec must contain exactly: {', '.join(sorted(required))}")
        for key in ("sources","steps","approval_boundaries"):
            values=spec[key]
            if not isinstance(values,list) or len(values)>50 or any(not isinstance(value,str) or len(value)>1000 for value in values):
                raise ValueError(f"{key} must be a bounded list of strings")
        if len(set(spec["sources"])) != len(spec["sources"]):
            raise ValueError("skill source IDs must be unique")
        for key in required - {"sources", "steps", "approval_boundaries"}:
            self._clean(spec[key], 5000)
        normalized = json.dumps(spec, ensure_ascii=False)
        if len(normalized)>20000:raise ValueError("serialized skill exceeds 20 KB")
        skill_id = "skill_" + uuid.uuid4().hex
        now = datetime.now().astimezone().isoformat()
        if self._oracle is not None:
            self._oracle.save_skill(skill_id, name, workflow, normalized, now)
        else:
            with sqlite3.connect(self.database) as db:
                db.execute("INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?)", (skill_id, name, workflow, normalized, now))
        return {"skill_id": skill_id, "name": name, "workflow": workflow, "spec": spec,
                "approval_boundary_required": True}

    def list_skills(self) -> list[dict]:
        if self._oracle is not None:
            return self._oracle.list_skills()
        with sqlite3.connect(self.database) as db: rows = db.execute("SELECT id,name,workflow,spec,created_at FROM skills ORDER BY created_at DESC").fetchall()
        return [{"skill_id": a, "name": b, "workflow": c, "spec": json.loads(d), "created_at": e} for a,b,c,d,e in rows]

    def create_routine(self, skill_id: str, weekdays: list[int], local_time: str,
                       timezone_name: str, max_snapshot_age_hours: float = 24.0) -> dict:
        if not skill_id.startswith("skill_") or not weekdays or len(weekdays)>7 or len(set(weekdays))!=len(weekdays) or any(not isinstance(d,int) or not 0<=d<=6 for d in weekdays):
            raise ValueError("skill ID and unique weekdays 0-6 required")
        try: zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, TypeError) as error: raise ValueError("valid IANA timezone required") from error
        if isinstance(max_snapshot_age_hours, bool) or not isinstance(max_snapshot_age_hours, (int,float)) or not math.isfinite(max_snapshot_age_hours) or not 0.25 <= max_snapshot_age_hours <= 720:
            raise ValueError("max snapshot age must be between 0.25 and 720 hours")
        try: clock = time.fromisoformat(local_time)
        except ValueError as error: raise ValueError("local_time must be HH:MM[:SS]") from error
        if clock.tzinfo: raise ValueError("local_time must be wall time in the chosen timezone")
        routine_id = "routine_" + uuid.uuid4().hex
        created = datetime.now(zone).isoformat()
        if self._oracle is not None:
            if not self._oracle.skill_exists(skill_id): raise KeyError(skill_id)
            self._oracle.insert_routine(routine_id, skill_id, json.dumps(sorted(weekdays)),
                                        local_time, timezone_name, created, max_snapshot_age_hours)
        else:
            with sqlite3.connect(self.database) as db:
                if not db.execute("SELECT 1 FROM skills WHERE id=?", (skill_id,)).fetchone(): raise KeyError(skill_id)
                db.execute("INSERT OR REPLACE INTO routines (id,skill_id,weekdays,local_time,timezone,enabled,last_run,created_at,max_age_hours) VALUES (?,?,?,?,?,?,?,?,?)",
                           (routine_id,skill_id,json.dumps(sorted(weekdays)),local_time,timezone_name,1,None,created,max_snapshot_age_hours))
        return {"routine_id": routine_id, "skill_id": skill_id, "weekdays": sorted(weekdays),
                "local_time": local_time, "timezone": timezone_name, "enabled": True,
                "max_snapshot_age_hours": max_snapshot_age_hours,
                "execution": "local process scheduler when FRIDAY_ENABLE_ROUTINES=1; requires a fresh snapshot; never sends or edits"}

    def next_run(self, routine_id: str, after: datetime | None = None) -> dict:
        if self._oracle is not None:
            routine = self._oracle.get_routine(routine_id)
        else:
            with sqlite3.connect(self.database) as db:
                row=db.execute("SELECT weekdays,local_time,timezone,enabled,last_run,max_age_hours FROM routines WHERE id=?",(routine_id,)).fetchone()
            routine = None if row is None else dict(zip(
                ("weekdays", "local_time", "timezone", "enabled", "last_run", "max_age_hours"), row))
        if routine is None: raise KeyError(routine_id)
        weekdays, local_clock, zone_name, enabled, last_run, max_age_hours = (
            routine["weekdays"], routine["local_time"], routine["timezone"], routine["enabled"],
            routine["last_run"], routine["max_age_hours"])
        if not enabled: return {"routine_id":routine_id,"enabled":False,"next_run":None}
        zone=ZoneInfo(zone_name); now=(after or datetime.now(zone)).astimezone(zone)
        target_time=time.fromisoformat(local_clock); chosen=None
        for offset in range(8):
            day=(now+timedelta(days=offset)).date()
            candidate=datetime.combine(day,target_time,zone)
            if day.weekday() in json.loads(weekdays) and candidate>now and (not last_run or candidate.isoformat()>last_run):
                chosen=candidate;break
        return {"routine_id":routine_id,"enabled":True,"next_run":chosen.isoformat() if chosen else None,
                "timezone":zone_name,"max_snapshot_age_hours":max_age_hours,
                "schedule": "local process scheduler when FRIDAY_ENABLE_ROUTINES=1; also callable manually"}

    def ingest_snapshot(self, source_id: str, payload: dict | list, observed_at: str | None = None,
                        source_link: str = "") -> dict:
        source_id = self._clean(source_id, 100)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", source_id):
            raise ValueError("source_id must be a safe identifier")
        if not isinstance(payload, (dict,list)):
            raise ValueError("snapshot payload must be an object or list")
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(body) > 1_000_000: raise ValueError("snapshot exceeds one megabyte")
        stamp = observed_at or datetime.now().astimezone().isoformat()
        parsed = self._date(stamp,"observed_at",ZoneInfo("UTC"))
        if parsed is None: raise ValueError("observed_at is required")
        source_link = self._clean(source_link,1000)
        if self._oracle is not None:
            self._oracle.ingest_snapshot(source_id, parsed.isoformat(), body, source_link or None)
        else:
            with sqlite3.connect(self.database) as db:
                db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",(source_id,parsed.isoformat(),body,source_link or None))
                db.execute("DELETE FROM snapshots WHERE source_id=? AND observed_at NOT IN (SELECT observed_at FROM snapshots WHERE source_id=? ORDER BY observed_at DESC LIMIT 10)",(source_id,source_id))
        return {"source_id":source_id,"observed_at":parsed.isoformat(),"bytes":len(body.encode()),"stored":True}

    def _snapshot_data(self, routine_id: str, spec: dict, max_age_hours: float,
                       now: datetime) -> tuple[dict | None, dict]:
        source_ids=spec.get("sources",[])
        if not source_ids:
            return None,{"status":"blocked_missing_sources","missing_sources":["skill has no configured source IDs"]}
        data={}; freshness={}; missing=[]; stale=[]
        for source_id in source_ids:
            if self._oracle is not None:
                rows=[(r["observed_at"], r["payload"], r["source_link"])
                      for r in self._oracle.snapshot_rows(source_id)]
            else:
                with sqlite3.connect(self.database) as db:
                    rows=db.execute("SELECT observed_at,payload,source_link FROM snapshots WHERE source_id=? ORDER BY observed_at DESC LIMIT 10",(source_id,)).fetchall()
            candidates=[]
            for stamp,body,link in rows:
                parsed=self._date(stamp,"observed_at",ZoneInfo("UTC"))
                if parsed: candidates.append((parsed,json.loads(body),link))
            if not candidates:
                missing.append(source_id);continue
            observed,payload,link=max(candidates,key=lambda x:x[0].timestamp())
            age=(now.astimezone(ZoneInfo("UTC"))-observed.astimezone(ZoneInfo("UTC"))).total_seconds()/3600
            freshness[source_id]={"observed_at":observed.isoformat(),"age_hours":max(age,0),"source_link":link}
            if age>max_age_hours:
                stale.append(source_id);continue
            if isinstance(payload,dict): data.update(payload)
            elif isinstance(payload,list):
                key=source_id.casefold()
                alias={"crm":"leads","lead":"leads","leads":"leads","ad":"campaigns","ads":"campaigns","campaign":"campaigns","campaigns":"campaigns","task":"tasks","tasks":"tasks"}.get(key)
                if alias: data[alias]=payload
        if missing:return None,{"status":"blocked_missing_sources","missing_sources":missing,"freshness":freshness}
        if stale:return None,{"status":"blocked_stale_sources","stale_sources":stale,"freshness":freshness}
        return data,{"status":"ready","freshness":freshness}

    def run_routine(self, routine_id: str, data: dict[str, Any] | None = None,
                    generated_at: datetime | None = None) -> dict:
        if self._oracle is not None:
            routine = self._oracle.routine_skill(routine_id)
        else:
            with sqlite3.connect(self.database) as db:
                row=db.execute("SELECT s.workflow,s.spec,r.enabled,r.max_age_hours FROM routines r JOIN skills s ON s.id=r.skill_id WHERE r.id=?",(routine_id,)).fetchone()
            routine = None if row is None else {"workflow": row[0], "spec": row[1],
                                                "enabled": bool(row[2]), "max_age_hours": row[3]}
        if routine is None: raise KeyError(routine_id)
        workflow, spec_json, enabled, max_age_hours = (
            routine["workflow"], routine["spec"], routine["enabled"], routine["max_age_hours"])
        if not enabled: raise ValueError("routine is disabled")
        now=generated_at or datetime.now().astimezone()
        if data is None:
            data,source_state=self._snapshot_data(routine_id,json.loads(spec_json),max_age_hours,now)
        else:
            source_state={"status":"manual_snapshot","freshness":"caller supplied"}
        if data is None:
            generated=now.isoformat()
            result={"workflow":workflow,"status":source_state["status"],"generated_at":generated,
                    "output":source_state,"assumptions":["Required current snapshots are missing or stale."],
                    "external_actions_taken":[]}
        else:
            workflow_run=self.run(workflow,data)
            result=asdict(workflow_run)
            result["output"].setdefault("snapshot_freshness",source_state.get("freshness"))
        run_id="run_"+uuid.uuid4().hex
        if self._oracle is not None:
            self._oracle.insert_run(run_id, routine_id, workflow, result["status"],
                                    result["generated_at"], json.dumps(result))
            self._oracle.update_last_run(routine_id, result["generated_at"])
        else:
            with sqlite3.connect(self.database) as db:
                db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)",(run_id,routine_id,workflow,result["status"],result["generated_at"],json.dumps(result)))
                db.execute("UPDATE routines SET last_run=? WHERE id=?",(result["generated_at"],routine_id))
        return {"run_id":run_id,**result}

    def run_due(self, routine_id: str, now: datetime | None = None) -> dict | None:
        """Atomically claim one due wall-clock slot across concurrent API workers."""
        current=now or datetime.now().astimezone()
        if self._oracle is not None:
            claimed = self._oracle.claim_due_slot(routine_id, current, self._date)
            if claimed is None:
                return None
            slot, _, _ = claimed
        else:
            with sqlite3.connect(self.database,timeout=10) as db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT weekdays,local_time,timezone,enabled,last_run,max_age_hours,skill_id FROM routines WHERE id=?",(routine_id,)).fetchone()
                if not row:
                    db.rollback();raise KeyError(routine_id)
                weekdays,local_clock,zone_name,enabled,last_run,max_age,skill_id=row
                if not enabled:
                    db.rollback();return None
                zone=ZoneInfo(zone_name); local_now=current.astimezone(zone); last=self._date(last_run,"last_run",ZoneInfo("UTC")) if last_run else None
                target=time.fromisoformat(local_clock); slot=None
                for offset in range(8):
                    day=(local_now-timedelta(days=offset)).date()
                    candidate=datetime.combine(day,target,zone)
                    if day.weekday() in json.loads(weekdays) and candidate<=local_now and (last is None or candidate>last.astimezone(zone)):
                        slot=candidate;break
                if slot is None:
                    db.rollback();return None
                db.execute("UPDATE routines SET last_run=? WHERE id=?",(slot.isoformat(),routine_id))
                db.commit()
        result=self.run_routine(routine_id,data=None,generated_at=current)
        return {**result,"scheduled_for":slot.isoformat()}

    def run_due_all(self, now: datetime | None = None) -> list[dict]:
        due=[]
        for routine in self.list_routines():
            try:
                result=self.run_due(routine["routine_id"],now)
                if result: due.append(result)
            except Exception:
                # A single broken routine must not stop the polling scheduler.
                continue
        return due

    def start_scheduler(self, poll_seconds: float = 15) -> None:
        if not 5 <= poll_seconds <= 300: raise ValueError("scheduler poll interval must be 5-300 seconds")
        if self._scheduler_thread and self._scheduler_thread.is_alive(): return
        stop=Event();self._scheduler_stop=stop
        def loop():
            while not stop.is_set():
                self.run_due_all()
                stop.wait(poll_seconds)
        self._scheduler_thread=Thread(target=loop,name="friday-business-routines",daemon=True)
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        if self._scheduler_stop:self._scheduler_stop.set()
        if self._scheduler_thread:self._scheduler_thread.join(timeout=2)
        self._scheduler_thread=None;self._scheduler_stop=None

    def set_routine_enabled(self, routine_id: str, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if self._oracle is not None:
            changed = self._oracle.set_enabled(routine_id, enabled)
        else:
            with sqlite3.connect(self.database) as db:
                changed=db.execute("UPDATE routines SET enabled=? WHERE id=?",(int(enabled),routine_id)).rowcount
        if not changed:
            raise KeyError(routine_id)
        return {"routine_id":routine_id,"enabled":enabled}

    def list_routines(self) -> list[dict]:
        if self._oracle is not None:
            return self._oracle.list_routines()
        with sqlite3.connect(self.database) as db: rows=db.execute("SELECT id,skill_id,weekdays,local_time,timezone,enabled,last_run,max_age_hours FROM routines ORDER BY created_at DESC").fetchall()
        return [{"routine_id":r[0],"skill_id":r[1],"weekdays":json.loads(r[2]),"local_time":r[3],"timezone":r[4],"enabled":bool(r[5]),"last_run":r[6],"max_snapshot_age_hours":r[7]} for r in rows]
