from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.retrieval.scope import RetrievalScope
from app.tools.dispatcher import ToolDispatcher, ToolError


def test_search_tool_returns_previews_not_full_content_and_keeps_scope():
    scope = RetrievalScope(tenant_id="acme", principals=("engineers",))
    chunk_id, document_id = str(uuid4()), str(uuid4())
    candidate = {
        "chunk_id": chunk_id, "document_id": document_id,
        "document": "runbook.md", "page": None, "section": "Recovery",
        "content": "A" * 300,
    }
    with patch("app.tools.dispatcher.search_chunks", return_value=[candidate]) as search:
        result = ToolDispatcher(scope).execute(
            "search_documents", {"query": "payment recovery", "top_k": 2},
        )
    assert result.count == 1
    assert result.result[0]["preview"] == "A" * 200
    assert "content" not in result.result[0]
    assert search.call_args.kwargs["scope"] is scope


def test_read_tool_uses_same_sql_scope_and_preserves_requested_order():
    first, second, document_id = uuid4(), uuid4(), uuid4()
    scope = RetrievalScope(
        tenant_id="acme", principals=("engineers",),
        as_of=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )

    class Cursor:
        def execute(self, query, parameters):
            self.query, self.parameters = query, parameters

        def fetchall(self):
            return [
                (second, document_id, "guide.md", None, "Owners", "owner text", 1, None, None),
                (first, document_id, "guide.md", None, "Response", "response text", 1, None, None),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    @contextmanager
    def fake_connection():
        yield connection

    with patch("app.tools.dispatcher.database_connection", fake_connection):
        result = ToolDispatcher(scope).execute(
            "read_document_chunks", {"chunk_ids": [str(first), str(second)]},
        )
    assert [item["chunk_id"] for item in result.result] == [str(first), str(second)]
    assert "d.tenant_id = %s" in connection.cursor_instance.query
    assert "d.access_groups && %s::text[]" in connection.cursor_instance.query
    assert connection.cursor_instance.parameters[1] == "acme"
    assert connection.cursor_instance.parameters[2] == ["engineers"]


def test_read_denies_missing_and_unauthorized_chunks_identically():
    requested = uuid4()

    class Cursor:
        def execute(self, *_):
            pass

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def fake_connection():
        yield Connection()

    with patch("app.tools.dispatcher.database_connection", fake_connection):
        with pytest.raises(ToolError) as captured:
            ToolDispatcher(RetrievalScope()).execute(
                "read_document_chunks", {"chunk_ids": [str(requested)]},
            )
    assert captured.value.code == "not_found"


def test_dispatcher_rejects_unknown_tool_extra_arguments_and_call_overflow():
    dispatcher = ToolDispatcher(RetrievalScope(), max_calls=1)
    with pytest.raises(ToolError) as unknown:
        dispatcher.execute("delete_document", {"document_id": str(uuid4())})
    assert unknown.value.code == "unknown_tool"
    with pytest.raises(ToolError) as invalid:
        dispatcher.execute("search_documents", {"query": "payments", "tenant_id": "other"})
    assert invalid.value.code == "invalid_arguments"
    with patch("app.tools.dispatcher.search_chunks", return_value=[]):
        dispatcher.execute("search_documents", {"query": "payments"})
    with pytest.raises(ToolError) as limit:
        dispatcher.execute("search_documents", {"query": "payments"})
    assert limit.value.code == "call_limit"


def test_dispatcher_returns_controlled_dependency_error():
    with patch("app.tools.dispatcher.search_chunks", side_effect=ConnectionError("secret endpoint")):
        with pytest.raises(ToolError) as captured:
            ToolDispatcher(RetrievalScope()).execute(
                "search_documents", {"query": "payments"},
            )
    assert captured.value.code == "dependency_unavailable"
    assert "secret endpoint" not in str(captured.value)
