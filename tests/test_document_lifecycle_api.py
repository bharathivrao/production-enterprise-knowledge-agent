from unittest.mock import patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_delete_document():
    document_id = uuid4()
    with patch("app.api.ingest.delete_document", return_value=True):
        response = client.delete(f"/documents/{document_id}")
    assert response.status_code == 204


def test_delete_missing_document_returns_404():
    document_id = uuid4()
    with patch("app.api.ingest.delete_document", return_value=False):
        response = client.delete(f"/documents/{document_id}")
    assert response.status_code == 404


def test_reindex_legacy_document_requires_replacement():
    from app.ingestion.errors import InvalidDocumentError

    document_id = uuid4()
    with patch(
        "app.api.ingest.reindex_document",
        side_effect=InvalidDocumentError("legacy source missing"),
    ):
        response = client.post(f"/documents/{document_id}/reindex")
    assert response.status_code == 409


def test_upload_database_outage_is_controlled():
    with patch(
        "app.api.ingest.ingest_pdf",
        side_effect=psycopg.OperationalError("database offline"),
    ):
        response = client.post(
            "/documents",
            files={"file": ("notes.txt", b"text", "text/plain")},
        )
    assert response.status_code == 503


def test_known_oversized_request_is_rejected_before_parsing():
    response = client.post(
        "/documents",
        content=b"ignored",
        headers={"content-length": str(11 * 1024 * 1024)},
    )
    assert response.status_code == 413
