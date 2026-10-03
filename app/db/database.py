from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from app.core.config import get_settings


_pool: ConnectionPool | None = None


def _configure_connection(connection: Connection) -> None:
    register_vector(connection)
    connection.commit()


def start_database_pool() -> ConnectionPool:
    """Create and open the process-wide database connection pool."""
    global _pool
    if _pool is not None and not _pool.closed:
        return _pool

    settings = get_settings()
    if settings.postgres_pool_min_size > settings.postgres_pool_max_size:
        raise ValueError("postgres_pool_min_size cannot exceed postgres_pool_max_size")

    _pool = ConnectionPool(
        conninfo="",
        kwargs={
            "host": settings.postgres_host,
            "port": settings.postgres_port,
            "dbname": settings.postgres_db,
            "user": settings.postgres_user,
            "password": settings.postgres_password.get_secret_value(),
            "connect_timeout": settings.postgres_connect_timeout_seconds,
            "options": (
                f"-c statement_timeout={settings.postgres_statement_timeout_ms} "
                f"-c lock_timeout={settings.postgres_statement_timeout_ms}"
            ),
        },
        min_size=settings.postgres_pool_min_size,
        max_size=settings.postgres_pool_max_size,
        configure=_configure_connection,
        open=False,
        timeout=settings.postgres_connect_timeout_seconds,
        name="knowledge-agent-db",
    )
    _pool.open(wait=False)
    return _pool


def close_database_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_database_pool() -> ConnectionPool:
    if _pool is None or _pool.closed:
        return start_database_pool()
    return _pool


@contextmanager
def database_connection():
    with get_database_pool().connection() as connection:
        yield connection


def database_ready() -> bool:
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'vector'
                )
                """
            )
            row = cursor.fetchone()
    return bool(row and row[0])
