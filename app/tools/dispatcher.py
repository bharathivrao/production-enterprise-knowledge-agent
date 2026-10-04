"""Validated read-only tool boundary shared by the workflow and MCP server."""

from dataclasses import dataclass
from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.db.database import database_connection
from app.retrieval.scope import RetrievalScope, document_filter_sql
from app.retrieval.vector_search import search_chunks


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=300)
    top_k: int = Field(default=3, ge=1, le=3)


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_ids: list[UUID] = Field(min_length=1, max_length=3)


ToolName = Literal["search_documents", "read_document_chunks"]


@dataclass(frozen=True)
class ToolObservation:
    name: ToolName
    result: list[dict]
    elapsed_ms: float

    @property
    def count(self) -> int:
        return len(self.result)


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _search(arguments: SearchInput, scope: RetrievalScope) -> list[dict]:
    # The model sees only a short preview; full evidence requires an authorized read.
    candidates = search_chunks(arguments.query, top_k=arguments.top_k, scope=scope)
    return [{
        "chunk_id": item["chunk_id"],
        "document_id": item["document_id"],
        "document": item["document"],
        "page": item["page"],
        "section": item["section"],
        "preview": item["content"][:200],
    } for item in candidates]


def _read(arguments: ReadInput, scope: RetrievalScope) -> list[dict]:
    ids = list(dict.fromkeys(arguments.chunk_ids))
    filters, parameters = document_filter_sql(scope)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, d.id, d.filename, c.page, c.section, c.content,
                       d.document_version, d.conflict_group, d.valid_until
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE c.id = ANY(%s::uuid[]) AND """ + filters,
                [[str(value) for value in ids], *parameters],
            )
            rows = cursor.fetchall()
    by_id = {str(row[0]): {
        "chunk_id": str(row[0]), "document_id": str(row[1]),
        "document": row[2], "page": row[3], "section": row[4],
        "content": row[5], "document_version": row[6],
        "conflict_group": row[7], "valid_until": row[8],
    } for row in rows}
    # A missing or unauthorized ID is indistinguishable to the caller.
    if len(by_id) != len(ids):
        raise ToolError("not_found", "One or more chunks were not available")
    return [by_id[str(value)] for value in ids]


class ToolDispatcher:
    def __init__(
        self, scope: RetrievalScope, *, max_calls: int = 6,
        max_elapsed_seconds: float = 120.0,
    ):
        self.scope = scope
        self.max_calls = max_calls
        self.max_elapsed_seconds = max_elapsed_seconds
        self.calls = 0

    def execute(self, name: str, arguments: dict) -> ToolObservation:
        if name not in ("search_documents", "read_document_chunks"):
            raise ToolError("unknown_tool", "Tool is not allowlisted")
        if self.calls >= self.max_calls:
            raise ToolError("call_limit", "Tool call limit exceeded")
        try:
            if name == "search_documents":
                parsed = SearchInput.model_validate(arguments)
            else:
                parsed = ReadInput.model_validate(arguments)
        except (ValidationError, TypeError) as error:
            raise ToolError("invalid_arguments", "Invalid tool arguments") from error

        self.calls += 1
        started = perf_counter()
        try:
            if name == "search_documents":
                result = _search(parsed, self.scope)
            else:
                result = _read(parsed, self.scope)
        except ToolError:
            raise
        except (OSError, TimeoutError) as error:
            raise ToolError("dependency_unavailable", "Tool dependency unavailable") from error
        except Exception as error:
            raise ToolError("tool_failed", "Tool execution failed") from error
        elapsed = perf_counter() - started
        # Cooperative cap; database and model clients also enforce their timeouts.
        if elapsed > self.max_elapsed_seconds:
            raise ToolError("timeout", "Tool execution exceeded its time limit")
        return ToolObservation(name=name, result=result, elapsed_ms=elapsed * 1000)
