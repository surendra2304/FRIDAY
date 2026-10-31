"""Test-only SQLite helpers.

FRIDAY persists to Oracle Autonomous Database in every runtime path. The only
remaining SQLite code in this codebase is the explicitly-opted-in local store
used by the test suite (``FRIDAY_ENV=testing`` or a running pytest process) and
by developers who pass a path by hand.

To make that guarantee mechanical rather than a convention, every entry point in
this module refuses to run outside a test process:
:func:`friday.core.oracle.ephemeral_backend_allowed` gates the whole file. A
production process that somehow reaches a ``db_path`` branch raises
:class:`~friday.core.exceptions.PersistenceConfigError` instead of silently
creating a ``.db`` file on disk.

Nothing in the live request path may import from this module.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Iterator

from friday.core.exceptions import PersistenceConfigError
from friday.core.oracle import ephemeral_backend_allowed

DEFAULT_BUSY_TIMEOUT_MS = 5000


def _require_test_context(operation: str) -> None:
    """Fail closed unless this process is a test run.

    ``ephemeral_backend_allowed`` is True only when ``FRIDAY_ENV`` is
    ``testing``/``test`` or pytest is imported; production never qualifies.
    """
    if not ephemeral_backend_allowed():
        raise PersistenceConfigError(
            f"{operation} is test-only. FRIDAY persists to Oracle Autonomous Database; "
            "set DATABASE_URL (or FRIDAY_DATABASE_URL / FRIDAY_UNIVERSE_DB_URL) to an "
            "oracle+oracledb:// DSN owned by the FRIDAY schema user."
        )


def get_ephemeral_db_path(filename: str = "ephemeral.db") -> str:
    """Return a scratch SQLite path for an isolated test run.

    Prefers RAM-backed ``/dev/shm`` on Linux hosts that provide it so a test
    never writes to persistent VM storage; falls back to ``~/.friday``.
    """
    _require_test_context("get_ephemeral_db_path")
    if os.name != "nt" and os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
        return f"/dev/shm/{filename}"
    base_dir = Path.home() / ".friday"
    base_dir.mkdir(parents=True, exist_ok=True)
    return str(base_dir / filename)


def configure_sqlite_pragmas(
    conn: sqlite3.Connection,
    enable_wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> None:
    """Apply WAL/busy-timeout pragmas to an open test SQLite connection."""
    _require_test_context("configure_sqlite_pragmas")
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)};")
    conn.execute("PRAGMA foreign_keys = ON;")
    if enable_wal:
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
        except sqlite3.OperationalError:
            # In-memory databases or read-only filesystems may not support WAL mode
            pass


def connect_sqlite(
    db_path: str | Path,
    timeout: float = 5.0,
    enable_wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    row_factory: type | None = sqlite3.Row,
    check_same_thread: bool = False,
) -> sqlite3.Connection:
    """Create a configured SQLite connection for an explicit test path."""
    _require_test_context("connect_sqlite")
    path_str = str(db_path)
    if path_str != ":memory:":
        parent = Path(path_str).parent
        parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        path_str,
        timeout=timeout,
        check_same_thread=check_same_thread,
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    if row_factory is not None:
        conn.row_factory = row_factory

    configure_sqlite_pragmas(conn, enable_wal=enable_wal, busy_timeout_ms=busy_timeout_ms)
    return conn


@contextlib.contextmanager
def get_db_connection(
    db_path: str | Path,
    timeout: float = 5.0,
    enable_wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
) -> Iterator[sqlite3.Connection]:
    """Context manager for an explicit test SQLite path."""
    conn = connect_sqlite(
        db_path,
        timeout=timeout,
        enable_wal=enable_wal,
        busy_timeout_ms=busy_timeout_ms,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
