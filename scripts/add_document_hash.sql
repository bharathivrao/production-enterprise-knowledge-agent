ALTER TABLE documents
ADD COLUMN content_hash TEXT;

ALTER TABLE documents
ADD CONSTRAINT documents_content_hash_format
CHECK (content_hash ~ '^[0-9a-f]{64}$');

ALTER TABLE documents
ADD CONSTRAINT documents_content_hash_unique
UNIQUE (content_hash);