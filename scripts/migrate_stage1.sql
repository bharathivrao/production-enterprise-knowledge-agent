-- Idempotent upgrade for databases created by the pre-Stage-1 schema.
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_bytes BYTEA;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parser_name TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS parser_version TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_size INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS index_fingerprint TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS section TEXT;
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding VECTOR(768);

ALTER TABLE document_chunks DROP CONSTRAINT IF EXISTS documents_content_hash_format;
ALTER TABLE document_chunks DROP CONSTRAINT IF EXISTS documents_content_hash_unique;
ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_hash;
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_content_hash_unique;
CREATE UNIQUE INDEX IF NOT EXISTS documents_content_hash_fingerprint_key
    ON documents (content_hash, index_fingerprint);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks (document_id);

-- Rows with NULL hashes/fingerprints remain isolated legacy rows. Replace them
-- through PUT /documents/{id} to restore source bytes and full provenance.
