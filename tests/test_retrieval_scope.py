from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.retrieval.scope import RetrievalScope, document_filter_sql


def test_scope_builds_tenant_permission_time_and_metadata_filters():
    document_id = uuid4()
    scope = RetrievalScope(
        tenant_id="acme",
        principals=("employees", "finance"),
        document_ids=(document_id,),
        content_types=("text/markdown",),
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    sql, parameters = document_filter_sql(scope)
    assert "d.tenant_id = %s" in sql
    assert "d.access_groups && %s::text[]" in sql
    assert "d.id = ANY(%s::uuid[])" in sql
    assert "d.content_type = ANY(%s::text[])" in sql
    assert parameters[0] == "acme"
    assert parameters[1] == ["employees", "finance"]
    assert parameters[-2] == [str(document_id)]


def test_scope_rejects_empty_principals():
    with pytest.raises(ValueError, match="principal"):
        document_filter_sql(RetrievalScope(principals=()))
