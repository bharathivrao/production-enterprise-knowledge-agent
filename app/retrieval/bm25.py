import re
from rank_bm25 import BM25Okapi

from app.db.database import database_connection
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope, document_filter_sql


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "get", "how", "i", "in", "is", "it", "me", "my", "of", "on",
    "or", "that", "the", "this", "to", "was", "were", "what", "with",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"\w+", text.lower())
    return [word for word in words if word not in STOP_WORDS]


def search_keyword(
    query: str,
    top_k: int = 5,
    *,
    scope: RetrievalScope = PUBLIC_SCOPE,
) -> list[dict]:
    """Search the maintained PostgreSQL full-text GIN index.

    PostgreSQL uses `ts_rank_cd`, not the BM25 formula. `search_bm25` remains as
    a compatibility alias while reports identify this implementation as
    `postgres_fts`.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    tsquery = " | ".join(query_tokens)

    filters, filter_parameters = document_filter_sql(scope)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH parsed_query AS (
                    SELECT to_tsquery('english', %s) AS value
                )
                SELECT
                    c.id, d.id, d.filename, c.page, c.section, c.content,
                    d.document_version, d.conflict_group, d.valid_until,
                    ts_rank_cd(c.search_vector, parsed_query.value) AS score
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                CROSS JOIN parsed_query
                WHERE c.search_vector @@ parsed_query.value
                  AND """ + filters + """
                ORDER BY score DESC, c.id
                LIMIT %s
                """,
                [tsquery, *filter_parameters, top_k],
            )
            rows = cursor.fetchall()

    return [
        {
            "chunk_id": str(row[0]), "document_id": str(row[1]),
            "document": row[2], "page": row[3], "section": row[4],
            "content": row[5], "document_version": row[6],
            "conflict_group": row[7], "valid_until": row[8],
            "keyword_score": float(row[9]),
            "bm25_score": float(row[9]),
        }
        for row in rows
    ]


def search_bm25(query: str, top_k: int = 5, *, scope: RetrievalScope = PUBLIC_SCOPE):
    return search_keyword(query, top_k=top_k, scope=scope)


def search_bm25_baseline(
    query: str,
    top_k: int = 5,
    *,
    scope: RetrievalScope = PUBLIC_SCOPE,
) -> list[dict]:
    """Evaluation-only legacy BM25; production uses the maintained FTS index."""
    if not query.strip():
        raise ValueError("query must not be blank")
    filters, parameters = document_filter_sql(scope)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, d.id, d.filename, c.page, c.section, c.content,
                       d.document_version, d.conflict_group, d.valid_until
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE """ + filters,
                parameters,
            )
            rows = cursor.fetchall()
    chunks = [
        {
            "chunk_id": str(row[0]), "document_id": str(row[1]),
            "document": row[2], "page": row[3], "section": row[4],
            "content": row[5], "document_version": row[6],
            "conflict_group": row[7], "valid_until": row[8],
        }
        for row in rows
    ]
    query_tokens = tokenize(query)
    tokenized = [tokenize(chunk["content"]) for chunk in chunks]
    if not chunks or not query_tokens or not any(tokenized):
        return []
    scores = BM25Okapi(tokenized).get_scores(query_tokens)
    ranked = sorted(range(len(chunks)), key=lambda index: scores[index], reverse=True)
    return [
        {**chunks[index], "bm25_score": float(scores[index])}
        for index in ranked[:top_k]
    ]
