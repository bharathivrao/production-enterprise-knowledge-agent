
import numpy as np
from app.core.model_client import model_client
from app.core.config import get_settings
from app.db.database import database_connection
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope, document_filter_sql

def search_chunks(query, top_k=5, *, scope: RetrievalScope = PUBLIC_SCOPE):
    settings = get_settings()

    if not query.strip():
        raise ValueError("query must not be blank")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")

    response = model_client.embed(
        model=settings.embedding_model,
        input=query,
        truncate=False,
    )

    query_vector = np.array(
        response["embeddings"][0],
        dtype=np.float32,
    )

    filters, filter_parameters = document_filter_sql(scope)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id,
                    d.id,
                    d.filename,
                    c.page,
                    c.section,
                    c.content,
                    d.document_version,
                    d.conflict_group,
                    d.valid_until,
                    c.embedding <=> %s AS distance
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                  AND """ + filters + """
                ORDER BY distance
                LIMIT %s
                """,
                [query_vector, *filter_parameters, top_k],
            )

            results = cursor.fetchall()

    return [
        {
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "document": filename,
            "page": page,
            "section": section,
            "content": content,
            "document_version": document_version,
            "conflict_group": conflict_group,
            "valid_until": valid_until,
            "distance": float(distance),
        }
        for (
            chunk_id, document_id, filename, page, section, content,
            document_version, conflict_group, valid_until, distance,
        ) in results
    ]
