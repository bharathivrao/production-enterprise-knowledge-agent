from hashlib import sha256
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.core.config import get_settings
from app.db.migrations import _apply_one, apply_migrations


pytestmark = pytest.mark.integration
if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("set RUN_POSTGRES_INTEGRATION=1", allow_module_level=True)


def _connection():
    settings = get_settings()
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        connect_timeout=settings.postgres_connect_timeout_seconds,
    )


def test_fresh_schema_migrates_once_and_failed_migration_rolls_back():
    schema = f"migration_test_{uuid4().hex}"
    with _connection() as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.commit()
        connection.execute(sql.SQL("SET search_path TO {}, public").format(
            sql.Identifier(schema),
        ))
        try:
            applied = apply_migrations(connection)
            assert applied == ["001_stage1", "002_stage2", "006_stage6", "008_stage8"]
            assert apply_migrations(connection) == []
            assert connection.execute(
                "SELECT count(*) FROM schema_migrations"
            ).fetchone()[0] == 5  # schema baseline + four checked migration versions
            assert connection.execute(
                "SELECT to_regclass('conversation_sessions') IS NOT NULL"
            ).fetchone()[0]

            failed_sql = "CREATE TABLE rollback_probe (id INTEGER); SELECT 1 / 0"
            checksum = sha256(failed_sql.encode()).hexdigest()
            with pytest.raises(psycopg.Error):
                _apply_one(connection, "test_failed", failed_sql, checksum)
            assert connection.execute(
                "SELECT to_regclass('rollback_probe') IS NULL"
            ).fetchone()[0]
            assert connection.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_id = 'test_failed'"
            ).fetchone() is None
        finally:
            connection.rollback()
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(
                sql.Identifier(schema),
            ))
