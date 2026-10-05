"""Transactional, checksum-verified database migrations for local deployments."""

from hashlib import sha256

import psycopg

from app.core.config import PROJECT_ROOT, get_settings


MIGRATIONS = (
    ("001_stage1", "scripts/migrate_stage1.sql"),
    ("002_stage2", "scripts/migrate_stage2.sql"),
    ("006_stage6", "scripts/migrate_stage6.sql"),
    ("008_stage8", "scripts/migrate_stage8.sql"),
)
LOCK_NAME = "production-enterprise-knowledge-agent-migrations"


def _source(relative_path: str) -> tuple[str, str]:
    body = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
    return body, sha256(body.encode("utf-8")).hexdigest()


def _apply_one(connection: psycopg.Connection, migration_id: str, sql: str,
               checksum: str) -> bool:
    with connection.transaction():
        previous = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE migration_id = %s",
            (migration_id,),
        ).fetchone()
        if previous:
            if previous[0] != checksum:
                raise RuntimeError(
                    f"Applied migration {migration_id} has changed; "
                    "restore its original file and add a new migration."
                )
            return False
        connection.execute(sql)
        connection.execute(
            "INSERT INTO schema_migrations (migration_id, checksum) VALUES (%s, %s)",
            (migration_id, checksum),
        )
    return True


def apply_migrations(connection: psycopg.Connection) -> list[str]:
    """Apply unapplied migrations in order; each file and ledger row is atomic."""
    applied: list[str] = []
    connection.execute("SELECT pg_advisory_lock(hashtext(%s))", (LOCK_NAME,))
    connection.commit()
    try:
        with connection.transaction():
            connection.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            has_documents = connection.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = 'documents' AND c.relkind = 'r'
                )
            """).fetchone()[0]
            if not has_documents:
                schema_sql, schema_checksum = _source("scripts/schema.sql")
                connection.execute(schema_sql)
                connection.execute(
                    "INSERT INTO schema_migrations (migration_id, checksum) VALUES (%s, %s)",
                    ("000_schema", schema_checksum),
                )
                # The fresh schema already contains the effects of these files.
                for migration_id, relative_path in MIGRATIONS:
                    _, checksum = _source(relative_path)
                    connection.execute(
                        "INSERT INTO schema_migrations (migration_id, checksum) VALUES (%s, %s)",
                        (migration_id, checksum),
                    )
                    applied.append(migration_id)

        if has_documents:
            for migration_id, relative_path in MIGRATIONS:
                sql, checksum = _source(relative_path)
                if _apply_one(connection, migration_id, sql, checksum):
                    applied.append(migration_id)
    finally:
        connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_NAME,))
        connection.commit()
    return applied


def main() -> None:
    settings = get_settings()
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        connect_timeout=settings.postgres_connect_timeout_seconds,
    ) as connection:
        applied = apply_migrations(connection)
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Database schema is up to date.")


if __name__ == "__main__":
    main()
