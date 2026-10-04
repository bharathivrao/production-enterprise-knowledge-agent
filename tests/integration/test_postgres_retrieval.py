import hashlib
import os
from uuid import uuid4

import pytest

from app.db.database import close_database_pool, database_connection
from app.db.repository import delete_document, store_document
from app.retrieval.bm25 import search_keyword
from app.retrieval.scope import RetrievalScope
from app.tools.dispatcher import ToolDispatcher, ToolError


pytestmark = pytest.mark.integration
if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("set RUN_POSTGRES_INTEGRATION=1", allow_module_level=True)


def _store(content, *, tenant="default", groups=("public",), version=1, conflict=None):
    fingerprint = hashlib.sha256(f"fp-{uuid4()}".encode()).hexdigest()
    content_hash = hashlib.sha256(f"{content}-{uuid4()}".encode()).hexdigest()
    return store_document(
        f"{uuid4()}.md", "text/markdown",
        [{"chunk_index": 0, "content": content, "page": None, "section": "Policy"}],
        [[0.01] * 768], content_hash=content_hash,
        provenance={
            "parser_name": "test", "parser_version": "1", "chunk_size": 100,
            "chunk_overlap": 10, "embedding_model": "test",
            "embedding_dimension": 768, "index_fingerprint": fingerprint,
        },
        tenant_id=tenant, access_groups=groups, document_version=version,
        conflict_group=conflict,
    )


def test_postgres_search_enforces_permissions_tenant_and_latest_version():
    ids = []
    try:
        ids.append(_store("zebracode old retry count three", version=1, conflict="retry"))
        ids.append(_store("zebracode current retry count two", version=2, conflict="retry"))
        ids.append(_store("zebracode finance secret", groups=("finance",)))
        ids.append(_store("zebracode other tenant", tenant="other"))

        public = search_keyword("zebracode", top_k=10)
        assert {result["content"] for result in public} == {
            "zebracode current retry count two"
        }

        finance = search_keyword(
            "zebracode", top_k=10,
            scope=RetrievalScope(principals=("public", "finance")),
        )
        assert {result["content"] for result in finance} == {
            "zebracode current retry count two", "zebracode finance secret",
        }
    finally:
        for document_id in ids:
            if document_id:
                delete_document(document_id)
        close_database_pool()


def test_scoped_read_tool_blocks_private_other_tenant_and_stale_chunks():
    ids = []
    try:
        ids.append(_store("private stage5 content", groups=("finance",)))
        ids.append(_store("other tenant stage5 content", tenant="other"))
        ids.append(_store("old stage5 content", version=1, conflict="stage5-version"))
        ids.append(_store("current stage5 content", version=2, conflict="stage5-version"))
        with database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT document_id, id FROM document_chunks WHERE document_id = ANY(%s::uuid[])",
                    [[str(value) for value in ids]],
                )
                chunk_ids = {str(document): str(chunk) for document, chunk in cursor.fetchall()}

        dispatcher = ToolDispatcher(RetrievalScope())
        current = dispatcher.execute(
            "read_document_chunks", {"chunk_ids": [chunk_ids[str(ids[3])]]},
        )
        assert current.result[0]["content"] == "current stage5 content"
        for document_id in ids[:3]:
            with pytest.raises(ToolError) as denied:
                dispatcher.execute(
                    "read_document_chunks", {"chunk_ids": [chunk_ids[str(document_id)]]},
                )
            assert denied.value.code == "not_found"
    finally:
        for document_id in ids:
            if document_id:
                delete_document(document_id)
        close_database_pool()
