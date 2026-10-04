import os
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.db.database import close_database_pool, database_connection
from app.memory.conversation_memory import (
    SessionConflict, SessionNotFound, append_turn, create_session,
    delete_session, load_session, purge_expired_sessions, reset_session,
    visible_source_titles,
)
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope


pytestmark = pytest.mark.integration
if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("set RUN_POSTGRES_INTEGRATION=1", allow_module_level=True)


def _append(created, version, question):
    return append_turn(
        created.session_id, created.session_token, scope=PUBLIC_SCOPE,
        expected_version=version, user_question=question,
        resolved_question=question, answer="Grounded answer [S1]",
        citations=[{"source_id": "S1", "document": "guide.md", "page": None}],
        state="completed",
    )


def test_session_capability_isolation_concurrency_reset_and_delete():
    first = create_session(scope=PUBLIC_SCOPE)
    second = create_session(scope=PUBLIC_SCOPE)
    try:
        with pytest.raises(SessionNotFound):
            load_session(first.session_id, second.session_token, scope=PUBLIC_SCOPE)
        with pytest.raises(SessionNotFound):
            load_session(
                first.session_id, first.session_token,
                scope=RetrievalScope(tenant_id="another-tenant"),
            )
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT token_hash FROM conversation_sessions WHERE id = %s",
                    (first.session_id,),
                )
                assert cursor.fetchone()[0] != first.session_token

        _append(first, 0, "Who owns payments?")
        with pytest.raises(SessionConflict):
            _append(first, 0, "Concurrent stale turn")
        snapshot = load_session(first.session_id, first.session_token, scope=PUBLIC_SCOPE)
        assert snapshot.version == 1
        assert len(snapshot.turns) == 1
        assert snapshot.turns[0].citations[0]["document"] == "guide.md"
        assert load_session(second.session_id, second.session_token,
                            scope=PUBLIC_SCOPE).turns == []

        reset_session(first.session_id, first.session_token, scope=PUBLIC_SCOPE)
        snapshot = load_session(first.session_id, first.session_token, scope=PUBLIC_SCOPE)
        assert snapshot.version == 2 and snapshot.turns == []
        with pytest.raises(SessionConflict):
            _append(first, 1, "Started before reset")
        delete_session(first.session_id, first.session_token, scope=PUBLIC_SCOPE)
        with pytest.raises(SessionNotFound):
            load_session(first.session_id, first.session_token, scope=PUBLIC_SCOPE)
    finally:
        for created in (first, second):
            try:
                delete_session(created.session_id, created.session_token,
                               scope=PUBLIC_SCOPE)
            except SessionNotFound:
                pass
        close_database_pool()


def test_session_turn_retention_and_expiry_cleanup():
    created = create_session(scope=PUBLIC_SCOPE)
    settings = get_settings().model_copy(update={"session_max_stored_turns": 2})
    try:
        from unittest.mock import patch

        with patch("app.memory.conversation_memory.get_settings", return_value=settings):
            _append(created, 0, "first")
            _append(created, 1, "second")
            _append(created, 2, "third")
        snapshot = load_session(created.session_id, created.session_token,
                                scope=PUBLIC_SCOPE)
        assert [turn.user_question for turn in snapshot.turns] == ["second", "third"]

        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_sessions
                    SET created_at = CURRENT_TIMESTAMP - INTERVAL '2 days',
                        expires_at = CURRENT_TIMESTAMP - INTERVAL '1 day'
                    WHERE id = %s
                    """,
                    (created.session_id,),
                )
        with pytest.raises(SessionNotFound):
            load_session(created.session_id, created.session_token, scope=PUBLIC_SCOPE)
        assert purge_expired_sessions() >= 1
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM conversation_turns WHERE session_id = %s",
                    (created.session_id,),
                )
                assert cursor.fetchone()[0] == 0
    finally:
        try:
            delete_session(created.session_id, created.session_token,
                           scope=PUBLIC_SCOPE)
        except SessionNotFound:
            pass
        close_database_pool()


def test_remembered_source_titles_are_reauthorized_against_current_scope():
    ids = [uuid4() for _ in range(4)]
    names = [f"stage6-{value}.md" for value in ids]
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                for index, document_id in enumerate(ids):
                    cursor.execute(
                        """
                        INSERT INTO documents
                            (id, filename, content_type, tenant_id,
                             access_groups, conflict_group, document_version)
                        VALUES (%s, %s, 'text/markdown', %s, %s, %s, %s)
                        """,
                        (document_id, names[index],
                         "other" if index == 1 else "default",
                         ["finance"] if index == 2 else ["public"],
                         "stage6-version" if index in (0, 3) else None,
                         1 if index == 0 else 2),
                    )
        visible = visible_source_titles(set(names), scope=PUBLIC_SCOPE)
        assert visible == {names[3]}
    finally:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM documents WHERE id = ANY(%s::uuid[])",
                    [[str(value) for value in ids]],
                )
        close_database_pool()
