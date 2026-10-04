-- Stage 8 binds existing capability sessions to their creator. Legacy sessions
-- become inaccessible to authenticated subjects and expire on their old TTL.
ALTER TABLE conversation_sessions
    ADD COLUMN IF NOT EXISTS owner_subject TEXT NOT NULL DEFAULT 'legacy';

CREATE INDEX IF NOT EXISTS conversation_sessions_owner_idx
    ON conversation_sessions (tenant_id, owner_subject, expires_at);
