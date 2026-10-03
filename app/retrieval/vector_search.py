
import numpy as np
from app.core.model_client import model_client
from app.core.config import get_settings
from app.db.database import database_connection

def search_chunks(query, top_k=5):
    settings = get_settings()

    if not query.strip():
        raise ValueError("query must not be blank")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    response = model_client.embed(
        model=settings.embedding_model,
        input=query,
        truncate=False,
    )

    query_vector = np.array(
        response["embeddings"][0],
        dtype=np.float32,
    )

    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id,
                    d.filename,
                    c.page,
                    c.section,
                    c.content,
                    c.embedding <=> %s AS distance
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE c.embedding IS NOT NULL
                ORDER BY distance
                LIMIT %s
                """,
                (query_vector, top_k),
            )

            results = cursor.fetchall()

    return [
        {
            "chunk_id": str(chunk_id),
            "document": filename,
            "page": page,
            "section": section,
            "content": content,
            "distance": float(distance),
        }
        for chunk_id, filename, page, section, content, distance in results
    ]
