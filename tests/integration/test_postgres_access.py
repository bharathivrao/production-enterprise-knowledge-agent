"""Real PostgreSQL checks for tenant, group, and session-owner boundaries."""

import os
from hashlib import sha256
from uuid import uuid4

import pytest

from app.db.database import close_database_pool, database_connection
from app.db.repository import (
    delete_document, find_document_by_hash, get_document_source,
)
from app.memory.conversation_memory import (
    SessionNotFound, create_session, delete_session, load_session,
)
from app.retrieval.scope import RetrievalScope


pytestmark = pytest.mark.integration
if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("set RUN_POSTGRES_INTEGRATION=1", allow_module_level=True)


def test_document_lookup_and_delete_respect_tenant_and_group():
    first_id, second_id = uuid4(), uuid4()
    digest = sha256(b"same bytes").hexdigest()
    fingerprint = sha256(b"same configuration").hexdigest()
    owner = RetrievalScope(tenant_id="stage8-a", principals=("team-a",))
    other_group = RetrievalScope(tenant_id="stage8-a", principals=("team-b",))
    other_tenant = RetrievalScope(tenant_id="stage8-b", principals=("team-a",))
    try:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                for document_id, tenant in ((first_id, "stage8-a"),
                                            (second_id, "stage8-b")):
                    cursor.execute(
                        """
                        INSERT INTO documents
                            (id, filename, content_type, content_hash,
                             index_fingerprint, source_bytes, tenant_id, access_groups)
                        VALUES (%s, 'private.md', 'text/markdown', %s, %s,
                                %s, %s, ARRAY['team-a']::text[])
                        """,
                        (document_id, digest, fingerprint, b"same bytes", tenant),
                    )
        assert find_document_by_hash(
            digest, tenant_id="stage8-a", scope=owner,
        )["document_id"] == str(first_id)
        assert find_document_by_hash(
            digest, tenant_id="stage8-a", scope=other_group,
        ) is None
        assert get_document_source(first_id, scope=other_group) is None
        assert get_document_source(first_id, scope=other_tenant) is None
        assert delete_document(first_id, scope=other_group) is False
        assert delete_document(first_id, scope=other_tenant) is False
        assert get_document_source(first_id, scope=owner)["source_bytes"] == b"same bytes"
        assert delete_document(first_id, scope=owner) is True
        assert find_document_by_hash(
            digest, tenant_id="stage8-b", scope=other_tenant,
        )["document_id"] == str(second_id)
    finally:
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM documents WHERE id = ANY(%s::uuid[])",
                    [[str(first_id), str(second_id)]],
                )
        close_database_pool()


def test_session_requires_creator_even_with_bearer_capability():
    scope = RetrievalScope(tenant_id="stage8-sessions", principals=("team-a",))
    created = create_session(scope=scope, subject="alice")
    try:
        with pytest.raises(SessionNotFound):
            load_session(
                created.session_id, created.session_token,
                scope=scope, subject="bob",
            )
        with pytest.raises(SessionNotFound):
            delete_session(
                created.session_id, created.session_token,
                scope=scope, subject="bob",
            )
        assert load_session(
            created.session_id, created.session_token,
            scope=scope, subject="alice",
        ).session_id == created.session_id
    finally:
        delete_session(
            created.session_id, created.session_token,
            scope=scope, subject="alice",
        )
        close_database_pool()
