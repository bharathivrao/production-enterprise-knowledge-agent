from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


@dataclass(frozen=True)
class RetrievalScope:
    """Server-derived retrieval boundary; never populate from query text."""

    tenant_id: str = "default"
    principals: tuple[str, ...] = ("public",)
    document_ids: tuple[UUID, ...] | None = None
    content_types: tuple[str, ...] | None = None
    as_of: datetime | None = None

    def normalized_as_of(self) -> datetime:
        return self.as_of or datetime.now(timezone.utc)


PUBLIC_SCOPE = RetrievalScope()


def document_filter_sql(scope: RetrievalScope, *, alias: str = "d"):
    """Return a parameterized SQL fragment shared by every retriever."""
    if not scope.tenant_id.strip():
        raise ValueError("tenant_id must not be blank")
    if not scope.principals:
        raise ValueError("at least one principal is required")

    as_of = scope.normalized_as_of()
    clauses = [
        f"{alias}.tenant_id = %s",
        f"{alias}.access_groups && %s::text[]",
        f"({alias}.valid_from IS NULL OR {alias}.valid_from <= %s)",
        f"({alias}.valid_until IS NULL OR {alias}.valid_until > %s)",
        f"""NOT EXISTS (
            SELECT 1 FROM documents AS newer
            WHERE newer.tenant_id = {alias}.tenant_id
              AND newer.conflict_group = {alias}.conflict_group
              AND newer.document_version > {alias}.document_version
              AND newer.access_groups && %s::text[]
              AND (newer.valid_from IS NULL OR newer.valid_from <= %s)
              AND (newer.valid_until IS NULL OR newer.valid_until > %s)
        )""",
    ]
    parameters: list[object] = [
        scope.tenant_id, list(scope.principals), as_of, as_of,
        list(scope.principals), as_of, as_of,
    ]
    if scope.document_ids is not None:
        clauses.append(f"{alias}.id = ANY(%s::uuid[])")
        parameters.append([str(value) for value in scope.document_ids])
    if scope.content_types is not None:
        clauses.append(f"{alias}.content_type = ANY(%s::text[])")
        parameters.append(list(scope.content_types))
    return " AND ".join(clauses), parameters
