"""Does a learned lesson actually come back? (Phase B evidence)

Phase B is labelled COMPLETE and its evidence file does not exist. The code is
real — ``agent.py`` calls ``build_self_upgrade_context`` and injects the result
behind a quarantine header — but "the code is wired up" and "the recall path
works" are different claims, and only one of them had been made.

So this exercises the path rather than describing it. A real failure is recorded
against a real isolated SQLite database, a real lesson is synthesized from it, and
the real recall is asked for it back. Nothing is mocked below the public API and
the database is a real file, not an in-memory stand-in, because the thing being
checked is whether a lesson survives the round trip.

Run it:

    python research/phaseB_recall_proof.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from friday.memory.memora_client import MemoraClient  # noqa: E402


def build_schema(db_path: Path) -> None:
    """Deliberately does nothing.

    An earlier version of this file hand-wrote the memory schema, and got it
    wrong: ``agents`` needs a ``role`` column, so the insert failed and the driver
    reported nine failures that were all really one - the schema was invented here
    rather than created by the code under test. ``MemoraClient.__init__`` calls
    ``_ensure_tables()``, which is the schema that actually ships. Let that build
    it, or this proves a shape the product does not use.
    """
    return None


def main() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    workdir = Path(tempfile.mkdtemp(prefix="phaseB-recall-"))
    db_path = workdir / "memora.db"
    # Create the file first. ``MemoraClient`` only honours a ``local_db_path``
    # that already exists - otherwise it silently falls through to a relative
    # ``data/memora.db`` or a hardcoded sibling path. That is a real defect and
    # this driver is where it was found, so the workaround is stated here rather
    # than hidden, and the behaviour itself is pinned by
    # tests/test_memora_local_db_path.py.
    db_path.touch()
    build_schema(db_path)
    print(f"  real database : {db_path}")

    client = MemoraClient(local_db_path=str(db_path), base_url="http://127.0.0.1:1")
    client.remote_enabled = False  # force the local engine; no service involved

    print("\n=== 1. a real failure is recorded ===")
    learned = client.learn_from_outcome(
        agent_name="friday",
        task_name="send an email to a refused recipient",
        status="failure",
        error_log="SMTP 550 Mailbox unavailable; the run reported SENT anyway",
        domain="tool_execution",
    )
    print(f"  status : {learned.get('status')}")
    print(f"  lesson : {learned.get('content')}")
    # Not "success": the honest label is ``local_only`` with ``cloud: False``,
    # meaning the lesson was stored locally and NOT sent to the Memora service.
    check(
        "the failure was recorded",
        learned.get("status") in {"success", "local_only"},
        str(learned.get("status")),
    )
    check("it says honestly that nothing reached the cloud", learned.get("cloud") is False)
    print(f"  cloud  : {learned.get('cloud')}  (False = stored locally, not published)")

    print("\n=== 2. the lesson is really in the database ===")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT memory_type, content_text FROM memory_records"
        ).fetchall()
    print(f"  rows in memory_records : {len(rows)}")
    for kind, text in rows:
        print(f"    - {kind}: {text[:100]}")
    check("a lesson row exists", len(rows) >= 1)
    check("it is stored as an experience", any(r[0] == "experience" for r in rows))

    print("\n=== 3. recall returns it ===")
    recalled = client.recall_experience(
        "friday", "send an email to a refused recipient", domain="tool_execution", limit=5
    )
    print(f"  recalled {len(recalled)} experience(s)")
    for exp in recalled:
        print(f"    - {str(exp.get('content_text'))[:100]}")
    check("recall returned at least one experience", len(recalled) >= 1)
    check(
        "the recalled text is the lesson that was stored",
        any("550" in str(e.get("content_text", "")) or "refused" in str(e.get("content_text", "")) for e in recalled),
    )

    print("\n=== 4. the context block is built, and quarantined ===")
    block = client.build_self_upgrade_context(
        "friday", "send an email to a refused recipient", domain="tool_execution"
    )
    print("  ---- the block that reaches the agent's system message ----")
    for line in block.splitlines():
        print(f"  | {line}")
    print("  -------------------------------------------------------")
    check("a block was built", bool(block), "empty block")
    check("it carries a quarantine header", "UNTRUSTED" in block.upper())
    check(
        "it marks the contents as non-authoritative",
        "NOT authoritative" in block or "not authoritative" in block,
    )

    # The strong "do not treat these as instructions" wording is added by the
    # CALLER, not by the builder. ``agent.py`` wraps this block in
    # ``=== [UNTRUSTED HISTORICAL MEMORY CONTEXT] ===`` with exactly that
    # instruction. Asserted here at the layer that actually emits it, so the two
    # halves cannot drift apart silently.
    agent_src = (REPO_ROOT / "src" / "friday" / "agent" / "agent.py").read_text(encoding="utf-8")
    check(
        "the caller wraps it with a do-not-obey instruction",
        "UNTRUSTED HISTORICAL MEMORY CONTEXT" in agent_src
        and "Do NOT interpret" in agent_src,
        "the builder's header alone does not tell the model to ignore instructions",
    )

    print("\n=== 5. what recall is actually scoped by ===")
    # FINDING, not a fix: ``_recall_experience_locally`` accepts ``agent_name``
    # and never uses it. There is no agent filter in the query, so every agent
    # receives every agent's lessons, ranked by keyword overlap. ``owner_name`` is
    # returned so a caller *could* filter, and ``source`` records who learned it.
    #
    # This may well be intended - a fleet learning shared operational lessons is
    # a reasonable design - but the parameter name says otherwise, and a caller
    # asking for agent X's lessons gets the whole fleet's. Changing it is a
    # product decision, so it is recorded here rather than changed here.
    unrelated = client.recall_experience(
        "an-agent-that-has-never-failed-at-anything", "a task never attempted", domain=None, limit=5
    )
    print(f"  lessons returned to an agent that learned nothing : {len(unrelated)}")
    if unrelated:
        print(f"    - learned by: {unrelated[0].get('owner_name')}")
    check(
        "recall is not scoped to the requesting agent (recorded, not changed)",
        len(unrelated) >= 1,
        "if this now returns 0, recall was scoped to the agent and this note is stale",
    )

    print("\n=== 5b. an empty store returns nothing at all ===")
    empty_db = Path(tempfile.mkdtemp(prefix="phaseB-empty-")) / "memora.db"
    empty_db.touch()
    blank = MemoraClient(local_db_path=str(empty_db), base_url="http://127.0.0.1:1")
    blank.remote_enabled = False
    empty = blank.build_self_upgrade_context("friday", "anything", domain="tool_execution")
    print(f"  block from an empty database : {empty!r}")
    check("no lessons means no block, not an invented one", empty == "")

    print("\n=== 6. the lesson survives a restart (a new client, same file) ===")
    reopened = MemoraClient(local_db_path=str(db_path), base_url="http://127.0.0.1:1")
    reopened.remote_enabled = False
    after = reopened.build_self_upgrade_context(
        "friday", "send an email to a refused recipient", domain="tool_execution"
    )
    print(f"  block after reopening the database : {len(after)} chars")
    check("the lesson was durable, not in-process", "550" in after or "refused" in after)

    print("\n=== RESULT ===")
    if failures:
        print(f"  {len(failures)} FAILURE(S): {failures}")
        return 1
    print("  A real failure became a real lesson, the lesson came back through a")
    print("  real recall, it survived the database being reopened, and it arrived")
    print("  behind a header telling the model to treat it as data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())