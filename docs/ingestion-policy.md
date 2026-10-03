# Ingestion policy

The service accepts PDF, UTF-8 TXT, Markdown (`.md`/`.markdown`), and DOCX files up
to `MAX_UPLOAD_BYTES` (10 MiB by default). Extensions select parsers; malformed or
mislabeled content is rejected.

PDF text is extracted in page order with one-based page numbers. OCR is not
performed: scanned/image-only PDFs must be OCR-processed before upload.
Password-protected PDFs and documents with no extractable text are rejected.

TXT is one unpaginated source. Markdown is split at ATX headings and retains the
heading as section metadata. DOCX paragraphs and tables follow their body order;
the nearest preceding heading names the section, and table cells become
tab-separated rows. Headers, footers, comments, text boxes, tracked-deletion text,
embedded files, and images are not indexed.

Each document records source bytes, parser version, chunk size/overlap, embedding
model, and embedding dimension. Their deterministic fingerprint participates in
deduplication. Identical bytes and fingerprint reuse an index; a configuration
change atomically reindexes it. `PUT /documents/{id}` replaces content, `POST
/documents/{id}/reindex` rebuilds retained content, and `DELETE /documents/{id}`
removes the document and cascading chunks.

Pre-Stage-1 rows missing hashes or source bytes are legacy records. They do not
deduplicate and cannot be automatically reindexed; replace each via `PUT`. Until
Stage 8 adds tenants, deduplication is global. It must become tenant-scoped before
multi-tenant use.
