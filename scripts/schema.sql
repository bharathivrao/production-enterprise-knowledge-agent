CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_hash TEXT CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    source_bytes BYTEA,
    parser_name TEXT,
    parser_version TEXT,
    chunk_size INTEGER CHECK (chunk_size IS NULL OR chunk_size > 0),
    chunk_overlap INTEGER CHECK (chunk_overlap IS NULL OR chunk_overlap >= 0),
    embedding_model TEXT,
    embedding_dimension INTEGER CHECK (embedding_dimension IS NULL OR embedding_dimension > 0),
    index_fingerprint TEXT CHECK (index_fingerprint IS NULL OR index_fingerprint ~ '^[0-9a-f]{64}$'),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    access_groups TEXT[] NOT NULL DEFAULT ARRAY['public']::TEXT[],
    document_version INTEGER NOT NULL DEFAULT 1 CHECK (document_version > 0),
    conflict_group TEXT,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, content_hash, index_fingerprint),
    CHECK (cardinality(access_groups) > 0),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    page INTEGER CHECK (page IS NULL OR page > 0),
    section TEXT,
    embedding VECTOR(768),
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(content, ''))
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector
    ON document_chunks USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS conversation_sessions (
    id UUID PRIMARY KEY,
    token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    tenant_id TEXT NOT NULL,
    principals TEXT[] NOT NULL CHECK (cardinality(principals) > 0),
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL CHECK (turn_index > 0),
    user_question TEXT NOT NULL,
    resolved_question TEXT NOT NULL,
    answer TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    state TEXT NOT NULL CHECK (state IN ('completed', 'clarification')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS conversation_sessions_expiry_idx
    ON conversation_sessions (expires_at);
CREATE INDEX IF NOT EXISTS conversation_turns_recent_idx
    ON conversation_turns (session_id, turn_index DESC);
