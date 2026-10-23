"""Standard SQLite connection helper and pragma enforcement for high-concurrency WAL mode."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sqlite3
from typing import Iterator

DEFAULT_BUSY_TIMEOUT_MS = 5000


def get_ephemeral_db_path(filename: str = "ephemeral.db") -> str:
    """Return an ephemeral database path strictly adhering to Invariant 2 (Zero-Disk SQLite).

    In production environments (e.g. Linux OCI instances with /dev/shm tmpfs),
    all fallback or temporary databases MUST reside in RAM tmpfs (/dev/shm/<filename>).
    Zero bytes are written to persistent VM disks.
    For local development on Windows or systems without /dev/shm, it defaults to ~/.friday/<filename>.
    """
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
    """Apply resilient production pragmas to an open SQLite connection."""
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
    """Create and configure a production-ready SQLite connection.
    
    Ensures parent directories exist, sets busy timeouts, enables foreign keys,
    and switches to WAL journal mode for concurrent reads/writes without locking.
    """
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
    """Context manager for acquiring and closing a configured SQLite connection."""
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
