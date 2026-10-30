"""Factory for instantiating memory backends based on Settings.

Selection rules (production first):

* ``oracle`` (the default) persists to Oracle Autonomous Database. It requires a
  valid ``oracle+oracledb://`` DSN in ``DATABASE_URL`` / ``FRIDAY_DATABASE_URL``
  / ``FRIDAY_UNIVERSE_DB_URL``; when the DSN is missing the factory raises
  :class:`~friday.core.exceptions.PersistenceConfigError` rather than quietly
  writing a SQLite file.
* ``sqlite`` is honoured only for explicit local development, i.e. a caller that
  opted in by setting ``memory_backend="sqlite"`` or by constructing
  :class:`~friday.memory.sqlite.SQLiteConversationMemory` directly.
* ``in_memory`` / ``mock`` are ephemeral and allowed only outside production.
* ``mem0`` keeps the Mem0 adapter but backs it with Oracle instead of SQLite.

The single fallback that still exists is the in-memory backend used by the test
suite (``FRIDAY_ENV=testing`` or a running pytest process) when no DSN is
configured. Production never takes that branch.
"""

from friday.core.config import Settings
from friday.core.exceptions import PersistenceConfigError
from friday.core.logging import get_logger
from friday.core.oracle import ephemeral_backend_allowed, resolve_database_url
from friday.memory.base import BaseMemory
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.oracle import OracleConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory

logger = get_logger("memory.factory")

_EPHEMERAL_BACKENDS = ("in_memory", "memory", "mock")


def _oracle_memory(
    settings: Settings,
    conversation_id: str | None,
    embedding_provider: object,
) -> OracleConversationMemory:
    """Build the Oracle backend, failing closed when the DSN is unusable."""
    dsn = settings.oracle_dsn
    if not dsn:
        configured = resolve_database_url(settings.database_url)
        if configured:
            raise PersistenceConfigError(
                "memory_backend='oracle' requires an Oracle DSN; the configured "
                f"database URL uses scheme '{configured.split('://', 1)[0]}://'. "
                "Set DATABASE_URL to an oracle+oracledb:// DSN owned by the FRIDAY schema."
            )
        raise PersistenceConfigError(
            "memory_backend='oracle' requires DATABASE_URL (or FRIDAY_DATABASE_URL / "
            "FRIDAY_UNIVERSE_DB_URL) to point at Oracle Autonomous Database. "
            "FRIDAY no longer falls back to a local SQLite file in production."
        )
    logger.debug("Initializing OracleConversationMemory (schema FRIDAY)")
    return OracleConversationMemory(
        conversation_id=conversation_id,
        max_messages=settings.memory_max_messages,
        embedding_provider=embedding_provider,
        dsn=dsn,
    )


def create_memory(
    settings: Settings,
    conversation_id: str | None = None,
) -> BaseMemory:
    """Instantiate and return the configured memory backend with optional embedding provider."""
    embedding_provider = create_embedding_provider(settings)
    backend = settings.memory_backend_kind

    if backend == "oracle":
        try:
            return _oracle_memory(settings, conversation_id, embedding_provider)
        except PersistenceConfigError:
            if not ephemeral_backend_allowed():
                raise
            logger.warning(
                "Oracle DSN is not configured; using an ephemeral in-memory memory "
                "backend because this process is a test run."
            )
            return InMemoryConversationMemory(
                max_messages=settings.memory_max_messages,
                embedding_provider=embedding_provider,
            )

    if backend == "sqlite":
        logger.warning(
            "memory_backend='sqlite' is for local development only; dashboard data "
            "in '%s' is not the production store.",
            settings.memory_db_path,
        )
        return SQLiteConversationMemory(
            db_path=settings.memory_db_path,
            conversation_id=conversation_id,
            max_messages=settings.memory_max_messages,
            embedding_provider=embedding_provider,
        )

    if backend == "mem0":
        logger.debug("Initializing Mem0MemoryAdapter with Oracle-backed fallback")
        from friday.memory.adapters.mem0_adapter import Mem0MemoryAdapter

        try:
            fallback_mem: BaseMemory = _oracle_memory(settings, conversation_id, embedding_provider)
        except PersistenceConfigError:
            if not ephemeral_backend_allowed():
                raise
            logger.warning("Mem0 fallback is ephemeral because no Oracle DSN is configured.")
            fallback_mem = InMemoryConversationMemory(
                max_messages=settings.memory_max_messages,
                embedding_provider=embedding_provider,
            )
        return Mem0MemoryAdapter(
            user_id="friday_user",
            fallback_memory=fallback_mem,
        )

    if backend in _EPHEMERAL_BACKENDS:
        if not ephemeral_backend_allowed():
            raise PersistenceConfigError(
                f"memory_backend='{backend}' is ephemeral and cannot be used outside a "
                "test run. Set DATABASE_URL to an oracle+oracledb:// DSN and leave "
                "memory_backend at its default ('oracle')."
            )
        logger.debug("Initializing InMemoryConversationMemory")
        return InMemoryConversationMemory(
            max_messages=settings.memory_max_messages,
            embedding_provider=embedding_provider,
        )

    raise PersistenceConfigError(
        f"Unknown memory backend '{backend}'. Supported values: 'oracle' (default), "
        "'sqlite' (local development only), 'mem0', 'in_memory'."
    )
