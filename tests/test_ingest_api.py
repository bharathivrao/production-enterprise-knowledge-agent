from unittest.mock import patch
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient

from app.ingestion.errors import InvalidDocumentError
from app.main import app

client = TestClient(app)


def test_upload_returns_created_document():
    expected = {
        "document_id": str(uuid4()),
        "filename": "sample.pdf",
        "chunk_count": 4,
        "created": True,
    }

    with patch(
        "app.api.ingest.ingest_pdf",
        return_value=expected,
    ) as ingest:
        response = client.post(
            "/documents",
            files={"file": ("sample.pdf", b"test content", "application/pdf")},
        )

    assert response.status_code == 201
    assert response.json() == expected
    ingest.assert_called_once()


def test_invalid_document_returns_422():
    with patch(
        "app.api.ingest.ingest_pdf",
        side_effect=InvalidDocumentError("The PDF is unreadable."),
    ):
        response = client.post(
            "/documents",
            files={"file": ("sample.pdf", b"bad content", "application/pdf")},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "The PDF is unreadable."}

def test_upload_returns_created_text():
    expected = {
        "document_id": str(uuid4()),
        "filename": "notes.txt",
        "chunk_count": 1,
        "created": True,
    }
    with patch("app.api.ingest.ingest_pdf", return_value=expected) as ingest:
        response = client.post(
            "/documents",
            files={"file": ("notes.txt", b"test content", "application/text")},
        )

    assert response.status_code == 201
    assert response.json() == expected
    ingest.assert_called_once()

def test_upload_reuses_existing_document():
    expected = {
        "document_id": str(uuid4()),
        "filename": "sample.pdf",
        "chunk_count": 4,
        "created": False,
    }

    with patch(
        "app.api.ingest.ingest_pdf",
        return_value=expected,
    ) as ingest:
        response = client.post(
            "/documents",
            files={"file": ("sample.pdf", b"test content", "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json() == expected
    ingest.assert_called_once()

def test_upload_returns_503_when_model_is_unavailable():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with (
        patch(
            "app.api.ingest.ingest_pdf",
            side_effect=ConnectionError("Ollama connection failed"),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/documents",
            files={
                "file": (
                    "example.pdf",
                    b"%PDF-1.4\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The model service is unavailable. Try again later."
    }

def test_upload_returns_504_when_model_times_out():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with (
        patch(
            "app.api.ingest.ingest_pdf",
            side_effect=httpx.ReadTimeout("Model response timed out"),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/documents",
            files={
                "file": (
                    "example.pdf",
                    b"%PDF-1.4\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "The model service timed out. Try again later."
    }
