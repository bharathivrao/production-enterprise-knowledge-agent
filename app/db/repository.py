from uuid import UUID, uuid4

import numpy as np

from app.core.config import get_settings
from app.db.database import database_connection


def _validate_chunks(chunks, embeddings) -> None:
    settings = get_settings()
    if not chunks:
        raise ValueError("Document produced no chunks")
    if len(embeddings) != len(chunks):
        raise ValueError("Embedding count does not match chunk count")
    if any(len(vector) != settings.embedding_dimension for vector in embeddings):
        raise ValueError(f"Expected {settings.embedding_dimension}-dimensional embeddings")


def _insert_chunks(cursor, document_id, chunks, embeddings) -> None:
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        cursor.execute(
            """
            INSERT INTO document_chunks
                (id, document_id, chunk_index, content, page, section, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(), document_id, chunk["chunk_index"], chunk["content"],
                chunk.get("page"), chunk.get("section"),
                np.array(embedding, dtype=np.float32),
            ),
        )


def store_document(filename, content_type, chunks, embeddings, *, content_hash,
                   source_bytes=None, provenance=None):
    _validate_chunks(chunks, embeddings)
    document_id = uuid4()
    provenance = provenance or {}
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO documents (
                    id, filename, content_type, content_hash, source_bytes,
                    parser_name, parser_version, chunk_size, chunk_overlap,
                    embedding_model, embedding_dimension, index_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (content_hash, index_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    document_id, filename, content_type, content_hash, source_bytes,
                    provenance.get("parser_name"), provenance.get("parser_version"),
                    provenance.get("chunk_size"), provenance.get("chunk_overlap"),
                    provenance.get("embedding_model"), provenance.get("embedding_dimension"),
                    provenance.get("index_fingerprint"),
                ),
            )
            if cursor.fetchone() is None:
                return None
            _insert_chunks(cursor, document_id, chunks, embeddings)
    return document_id


def replace_document_index(document_id, filename, content_type, chunks, embeddings,
                           *, content_hash, source_bytes, provenance):
    """Atomically replace metadata and chunks only after processing succeeds."""
    _validate_chunks(chunks, embeddings)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM documents WHERE id = %s FOR UPDATE", (document_id,))
            if cursor.fetchone() is None:
                return False
            cursor.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
            cursor.execute(
                """
                UPDATE documents SET
                    filename = %s, content_type = %s, content_hash = %s,
                    source_bytes = %s, parser_name = %s, parser_version = %s,
                    chunk_size = %s, chunk_overlap = %s, embedding_model = %s,
                    embedding_dimension = %s, index_fingerprint = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    filename, content_type, content_hash, source_bytes,
                    provenance["parser_name"], provenance["parser_version"],
                    provenance["chunk_size"], provenance["chunk_overlap"],
                    provenance["embedding_model"], provenance["embedding_dimension"],
                    provenance["index_fingerprint"], document_id,
                ),
            )
            _insert_chunks(cursor, document_id, chunks, embeddings)
    return True


def find_document_by_hash(content_hash, index_fingerprint=None):
    query = """
        SELECT d.id, d.filename, COUNT(c.id), d.index_fingerprint
        FROM documents AS d
        LEFT JOIN document_chunks AS c ON c.document_id = d.id
        WHERE d.content_hash = %s
    """
    parameters = [content_hash]
    if index_fingerprint is not None:
        query += " AND d.index_fingerprint = %s"
        parameters.append(index_fingerprint)
    query += " GROUP BY d.id, d.filename, d.index_fingerprint, d.created_at ORDER BY d.created_at LIMIT 1"
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()
    if row is None:
        return None
    return {
        "document_id": str(row[0]), "filename": row[1],
        "chunk_count": row[2], "index_fingerprint": row[3],
    }


def get_document_source(document_id: UUID | str):
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT filename, source_bytes FROM documents WHERE id = %s", (document_id,))
            row = cursor.fetchone()
    if row is None:
        return None
    return {"filename": row[0], "source_bytes": bytes(row[1]) if row[1] else None}


def delete_document(document_id: UUID | str) -> bool:
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            return cursor.rowcount == 1


def load_search_chunks():
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, d.filename, c.page, c.section, c.content
                FROM document_chunks AS c
                JOIN documents AS d ON d.id = c.document_id
                ORDER BY c.id
                """
            )
            rows = cursor.fetchall()
    return [
        {"chunk_id": str(row[0]), "document": row[1], "page": row[2],
         "section": row[3], "content": row[4]}
        for row in rows
    ]
