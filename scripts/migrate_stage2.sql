-- Stage 2: access-bound retrieval metadata and maintained PostgreSQL FTS index.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS access_groups TEXT[] NOT NULL DEFAULT ARRAY['public']::TEXT[];
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS conflict_group TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ;

DROP INDEX IF EXISTS documents_content_hash_fingerprint_key;
CREATE UNIQUE INDEX IF NOT EXISTS documents_tenant_hash_fingerprint_key
    ON documents (tenant_id, content_hash, index_fingerprint);
CREATE INDEX IF NOT EXISTS documents_retrieval_scope_idx
    ON documents (tenant_id, conflict_group, document_version DESC);

ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS search_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;
CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector
    ON document_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
