import hashlib
from unittest.mock import patch
from uuid import uuid4

from app.ingestion.pipeline import ingest_pdf
from types import SimpleNamespace


def test_storage_conflict_reuses_existing_document(tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"test document bytes")

    chunks = [
        {"chunk_index": 0, "page": 1, "content": "Test evidence"}
    ]
    embeddings = [[0.1] * 768]

    existing = {
        "document_id": str(uuid4()),
        "filename": "sample.pdf",
        "chunk_count": 1,
    }

    with (
        patch(
            "app.ingestion.pipeline.get_settings",
            return_value=SimpleNamespace(
                embedding_model="embeddinggemma"
            ),
        ),
        patch(
            "app.ingestion.pipeline.find_document_by_hash",
            side_effect=[None, existing],
        ) as lookup,
        patch(
            "app.ingestion.pipeline.prepare_document",
            return_value=chunks,
        ),
        patch(
            "app.ingestion.pipeline.model_client.embed",
            return_value={"embeddings": embeddings},
        ) as embed,
        patch(
            "app.ingestion.pipeline.store_document",
            return_value=None,
        ) as store,
    ):
        result = ingest_pdf(path)

    assert result == {**existing, "created": False}
    assert lookup.call_count == 2
    embed.assert_called_once()
    store.assert_called_once()

def test_existing_document_skips_processing(tmp_path):
    path = tmp_path / "renamed.pdf"
    path.write_bytes(b"same document bytes")

    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    existing = {
        "document_id": str(uuid4()),
        "filename": "original.pdf",
        "chunk_count": 4,
    }

    with (
        patch("app.ingestion.pipeline.get_settings"),
        patch(
            "app.ingestion.pipeline.find_document_by_hash",
            return_value=existing,
        ) as lookup,
        patch("app.ingestion.pipeline.prepare_document") as prepare,
        patch("app.ingestion.pipeline.model_client.embed") as embed,
        patch("app.ingestion.pipeline.store_document") as store,
    ):
        result = ingest_pdf(path)

    assert result == {**existing, "created": False}
    from app.retrieval.scope import PUBLIC_SCOPE
    lookup.assert_called_once_with(
        content_hash, tenant_id="default", scope=PUBLIC_SCOPE,
    )

    prepare.assert_not_called()
    store.assert_not_called()
    embed.assert_not_called()
