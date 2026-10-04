import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
from typing import Annotated

import httpx
import psycopg
from psycopg_pool import PoolTimeout
from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.repository import delete_document
from app.guardrails.auth import Actor, audit, require_document_manager, require_document_writer
from app.ingestion.errors import InvalidDocumentError
from app.ingestion.parser import content_type_for_filename
from app.ingestion.pipeline import ingest_pdf, reindex_document, replace_document


logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


def _document_access_groups(actor: Actor, requested: list[str] | None) -> tuple[str, ...]:
    if requested is None:
        return (f"user:{actor.subject}",)
    selected = tuple(dict.fromkeys(requested))
    allowed = set(actor.groups)
    if "document:publish" in actor.roles:
        allowed.add("public")
    if not selected or len(selected) > 32 or any(group not in allowed for group in selected):
        audit("document_access_assignment", "deny", actor)
        raise HTTPException(403, "Document access groups are not permitted.")
    return selected


class IngestResponse(BaseModel):
    document_id: UUID
    filename: str
    chunk_count: int = Field(ge=1)
    created: bool
    reindexed: bool = False


def _safe_filename(file: UploadFile) -> str:
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(415, "Upload PDF, TXT, Markdown, or DOCX.")
    try:
        content_type_for_filename(filename)
    except InvalidDocumentError as error:
        raise HTTPException(415, str(error)) from error
    return filename


def _stream_upload(file: UploadFile, path: Path) -> None:
    maximum = get_settings().max_upload_bytes
    total = 0
    with path.open("wb") as destination:
        while block := file.file.read(64 * 1024):
            total += len(block)
            if total > maximum:
                raise HTTPException(413, f"Document exceeds the {maximum} byte limit.")
            destination.write(block)
    if total == 0:
        raise HTTPException(422, "Uploaded file is empty.")


def _run_upload(file, operation):
    filename = _safe_filename(file)
    with TemporaryDirectory() as directory:
        path = Path(directory) / filename
        _stream_upload(file, path)
        try:
            return operation(path, filename)
        except InvalidDocumentError as error:
            raise HTTPException(422, str(error)) from error
        except ConnectionError as error:
            logger.exception("Model service connection failed")
            raise HTTPException(503, "The model service is unavailable. Try again later.") from error
        except httpx.TimeoutException as error:
            logger.exception("Model service request timed out")
            raise HTTPException(504, "The model service timed out. Try again later.") from error
        except psycopg.errors.UniqueViolation as error:
            raise HTTPException(
                409, "The same indexed content already exists as another document."
            ) from error
        except (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeout) as error:
            logger.exception("Database request failed")
            raise HTTPException(503, "The database is unavailable. Try again later.") from error


@router.post("/documents", response_model=IngestResponse, status_code=201,
             response_model_exclude_defaults=True)
def upload_document(
    file: UploadFile, response: Response,
    actor: Actor = Depends(require_document_writer),
    access_groups: Annotated[list[str] | None, Form()] = None,
):
    groups = _document_access_groups(actor, access_groups)
    result = _run_upload(file, lambda path, name: ingest_pdf(
        path, filename=name, scope=actor.scope, access_groups=groups,
    ))
    audit("document_create", "allow", actor)
    if not result["created"]:
        response.status_code = 200
    return result


@router.put("/documents/{document_id}", response_model=IngestResponse,
            response_model_exclude_defaults=True)
def replace_existing_document(
    document_id: UUID, file: UploadFile,
    actor: Actor = Depends(require_document_manager),
):
    result = _run_upload(
        file, lambda path, name: replace_document(
            document_id, path, filename=name, scope=actor.scope,
        )
    )
    if result is None:
        audit("document_replace", "deny", actor)
        raise HTTPException(404, "Document not found.")
    audit("document_replace", "allow", actor)
    return result


@router.post("/documents/{document_id}/reindex", response_model=IngestResponse,
             response_model_exclude_defaults=True)
def reindex_existing_document(
    document_id: UUID, actor: Actor = Depends(require_document_manager),
):
    try:
        result = reindex_document(document_id, scope=actor.scope)
    except InvalidDocumentError as error:
        raise HTTPException(409, str(error)) from error
    except ConnectionError as error:
        raise HTTPException(503, "The model service is unavailable. Try again later.") from error
    except httpx.TimeoutException as error:
        raise HTTPException(504, "The model service timed out. Try again later.") from error
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(
            409, "The same indexed content already exists as another document."
        ) from error
    except (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeout) as error:
        raise HTTPException(503, "The database is unavailable. Try again later.") from error
    if result is None:
        audit("document_reindex", "deny", actor)
        raise HTTPException(404, "Document not found.")
    audit("document_reindex", "allow", actor)
    return result


@router.delete("/documents/{document_id}", status_code=204)
def remove_document(
    document_id: UUID, actor: Actor = Depends(require_document_manager),
):
    try:
        removed = delete_document(document_id, scope=actor.scope)
    except (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeout) as error:
        raise HTTPException(503, "The database is unavailable. Try again later.") from error
    if not removed:
        audit("document_delete", "deny", actor)
        raise HTTPException(404, "Document not found.")
    audit("document_delete", "allow", actor)
    return Response(status_code=204)
