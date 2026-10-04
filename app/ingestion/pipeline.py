import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import get_settings
from app.core.model_client import model_client
from app.db.repository import (
    find_document_by_hash,
    get_document_source,
    replace_document_index,
    store_document,
)
from app.ingestion.chunker import chunk_pages
from app.ingestion.errors import InvalidDocumentError
from app.ingestion.parser import (
    PARSER_NAME, PARSER_VERSION, content_type_for_filename, parse_document,
)
from app.guardrails.injection import contains_embedded_instruction
from app.guardrails.pii import contains_credential, contains_high_risk_pii
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope


def _provenance(content_type, chunk_size, overlap) -> dict:
    settings = get_settings()
    embedding_dimension = getattr(settings, "embedding_dimension", 768)
    if not isinstance(embedding_dimension, int):
        embedding_dimension = 768
    embedding_model = getattr(settings, "embedding_model", "embeddinggemma")
    if not isinstance(embedding_model, str):
        embedding_model = "embeddinggemma"
    values = {
        "parser_name": PARSER_NAME, "parser_version": PARSER_VERSION,
        "content_type": content_type, "chunk_size": chunk_size,
        "chunk_overlap": overlap, "embedding_model": embedding_model,
        "embedding_dimension": embedding_dimension,
    }
    values["index_fingerprint"] = hashlib.sha256(
        json.dumps(values, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return values


def _integer_setting(settings, name, default):
    value = getattr(settings, name, default)
    return value if isinstance(value, int) else default


def prepare_document(file_path, chunk_size=500, overlap=50, *, filename=None):
    content_type, sources = parse_document(file_path, filename=filename)
    return content_type, chunk_pages(sources, chunk_size, overlap)


def _process(path, filename, chunk_size, overlap):
    settings = get_settings()
    prepared = prepare_document(path, chunk_size, overlap, filename=filename)
    if isinstance(prepared, tuple):
        content_type, chunks = prepared
    else:  # Compatibility for callers/tests written for the PDF-only pipeline.
        content_type, chunks = content_type_for_filename(filename), prepared
    if not chunks:
        message = "The document contains no extractable text."
        if content_type == "application/pdf":
            message += " Scanned PDFs require OCR before upload."
        raise InvalidDocumentError(message)
    for chunk in chunks:
        if contains_credential(chunk["content"]):
            raise InvalidDocumentError("Document contains credential-like content.")
        if contains_high_risk_pii(chunk["content"]):
            raise InvalidDocumentError("Document contains high-risk personal identifiers.")
        if contains_embedded_instruction(chunk["content"]):
            raise InvalidDocumentError("Document contains embedded control instructions.")
    response = model_client.embed(
        model=settings.embedding_model,
        input=[chunk["content"] for chunk in chunks],
        truncate=False,
    )
    return content_type, chunks, response["embeddings"]


def ingest_document(
    file_path, filename=None, chunk_size=None, overlap=None, *,
    scope: RetrievalScope = PUBLIC_SCOPE,
    access_groups: tuple[str, ...] = ("public",),
):
    path = Path(file_path)
    filename = filename or path.name
    settings = get_settings()
    chunk_size = _integer_setting(settings, "chunk_size", 500) if chunk_size is None else chunk_size
    overlap = _integer_setting(settings, "chunk_overlap", 50) if overlap is None else overlap
    content_type = content_type_for_filename(filename)
    provenance = _provenance(content_type, chunk_size, overlap)
    source_bytes = path.read_bytes()
    content_hash = hashlib.sha256(source_bytes).hexdigest()

    stale = find_document_by_hash(
        content_hash, tenant_id=scope.tenant_id, scope=scope,
    )
    if stale is not None and set(stale.get("access_groups", access_groups)) != set(access_groups):
        raise InvalidDocumentError(
            "The indexed content already exists with different access controls."
        )
    if stale is not None and (
        "index_fingerprint" not in stale
        or stale["index_fingerprint"] == provenance["index_fingerprint"]
    ):
        stale.pop("index_fingerprint", None)
        stale.pop("access_groups", None)
        return {**stale, "created": False}
    content_type, chunks, embeddings = _process(path, filename, chunk_size, overlap)
    if stale is not None and replace_document_index(
        stale["document_id"], filename, content_type, chunks, embeddings,
        content_hash=content_hash, source_bytes=source_bytes, provenance=provenance,
        scope=scope,
    ):
        return {
            "document_id": stale["document_id"], "filename": filename,
            "chunk_count": len(chunks), "created": False, "reindexed": True,
        }

    document_id = store_document(
        filename, content_type, chunks, embeddings,
        content_hash=content_hash, source_bytes=source_bytes, provenance=provenance,
        tenant_id=scope.tenant_id, access_groups=access_groups,
    )
    if document_id is None:
        existing = find_document_by_hash(
            content_hash, provenance["index_fingerprint"],
            tenant_id=scope.tenant_id, scope=scope,
        )
        if existing is None:
            raise InvalidDocumentError(
                "The indexed content already exists in this tenant."
            )
        if set(existing.get("access_groups", access_groups)) != set(access_groups):
            raise InvalidDocumentError(
                "The indexed content already exists with different access controls."
            )
        existing.pop("index_fingerprint", None)
        existing.pop("access_groups", None)
        return {**existing, "created": False}
    return {
        "document_id": str(document_id), "filename": filename,
        "chunk_count": len(chunks), "created": True,
    }


def replace_document(
    document_id, file_path, filename=None, *, scope: RetrievalScope = PUBLIC_SCOPE,
):
    path = Path(file_path)
    filename = filename or path.name
    settings = get_settings()
    content_type = content_type_for_filename(filename)
    chunk_size = _integer_setting(settings, "chunk_size", 500)
    chunk_overlap = _integer_setting(settings, "chunk_overlap", 50)
    provenance = _provenance(content_type, chunk_size, chunk_overlap)
    source_bytes = path.read_bytes()
    content_hash = hashlib.sha256(source_bytes).hexdigest()
    content_type, chunks, embeddings = _process(
        path, filename, chunk_size, chunk_overlap
    )
    if not replace_document_index(
        document_id, filename, content_type, chunks, embeddings,
        content_hash=content_hash, source_bytes=source_bytes, provenance=provenance,
        scope=scope,
    ):
        return None
    return {
        "document_id": str(document_id), "filename": filename,
        "chunk_count": len(chunks), "created": False, "reindexed": True,
    }


def reindex_document(document_id, *, scope: RetrievalScope = PUBLIC_SCOPE):
    source = get_document_source(document_id, scope=scope)
    if source is None:
        return None
    if not source["source_bytes"]:
        raise InvalidDocumentError(
            "This legacy document has no retained source. Replace it to reindex."
        )
    with TemporaryDirectory() as directory:
        path = Path(directory) / source["filename"]
        path.write_bytes(source["source_bytes"])
        return replace_document(document_id, path, source["filename"], scope=scope)


def ingest_pdf(
    file_path, filename=None, chunk_size=None, overlap=None, *,
    scope: RetrievalScope = PUBLIC_SCOPE,
    access_groups: tuple[str, ...] = ("public",),
):
    """Backward-compatible entry point; new code should use ingest_document."""
    return ingest_document(
        file_path, filename, chunk_size, overlap,
        scope=scope, access_groups=access_groups,
    )
