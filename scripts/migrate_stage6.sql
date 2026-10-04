-- Stage 6: bounded capability-protected conversation sessions.
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
