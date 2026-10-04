# Stage 6 working and conversation memory

Stage 6 adds an opt-in session API over the Stage 5 read-only tool workflow.
It is a local prototype, **not** user authentication or approval for real
enterprise data. The existing `/ask`, `/ask/planned`, and `/ask/tools` paths
remain stateless.

## Session API

1. `POST /sessions` creates a session and returns a UUID, expiry time, and
   one-time `session_token`. Keep the token private; it is a bearer capability.
2. Send `X-Session-Token` on `POST /sessions/{session_id}/ask` with a JSON body
   such as `{"query":"Who owns that service?","top_k":3}`.
3. `GET /sessions/{session_id}` returns the bounded turn history for that
   capability. `POST /sessions/{session_id}/reset` clears turns while keeping
   the session. `DELETE /sessions/{session_id}` deletes the session and turns.

The server derives the public retrieval scope; callers cannot supply tenant
or principals. Session token hashes, not plaintext tokens, are stored in
PostgreSQL. Incorrect token, wrong server scope, absent ID, and expired ID all
appear as `404 Session not found`. Session responses use `Cache-Control:
no-store`. There is no account identity, rate limit, or delegated tenant
authorization yet; those belong to Stage 8.

## Persistence, retention, and concurrency

`scripts/migrate_stage6.sql` adds `conversation_sessions` and
`conversation_turns`; fresh databases get the same tables from
`scripts/schema.sql`. Existing development databases need the migration:

```bash
docker compose exec -T db psql -v ON_ERROR_STOP=1 \
  -U knowledge_agent -d knowledge_agent -f /dev/stdin < scripts/migrate_stage6.sql
```

Default expiry is 24 hours from creation (not a sliding renewal). A session
stores at most 12 recent turns. Resolver context selects at most six recent
whole turns within 1,200 tokens; if the newest turn cannot fit, no older turn
is substituted. Expired sessions are inaccessible immediately and are deleted
on new-session creation or by the maintenance command:

```bash
.venv/bin/python -m app.memory.conversation_memory --purge-expired
```

Deletion cascades to turns. Persistence uses an optimistic version check:
concurrent turns based on the same history cannot silently overwrite one
another. The later writer receives HTTP 409 and must retry with fresh history.
Reset increments the version so an older in-flight answer also conflicts.
This avoids holding a database lock across slow model calls.

## Evidence boundary and working state

Per-request `WorkingMemory` records the question, resolved question, goal,
plan step IDs, tool statuses/counts, cited source metadata, and unresolved
clarification. It does not persist full tool result text. Stored turns retain
user questions, answers for display, resolved questions, and citation metadata.
The follow-up resolver receives **only previous user questions and currently
visible cited source titles**—not previous generated answers or resolved
questions. Source titles are reauthorized with the current tenant, access
group, validity, version, and document filters before entering the resolver.

A resolved follow-up is asked again through the current Stage 5 search/read
workflow. Previous citations are pointers for context, never substitute for
fresh source text. The first turn needs no resolver call; later turns use one
bounded structured resolver call. A vague reference may yield a clarification
without retrieval. Combined defaults are twelve model calls, 14,000 accounted
tokens, and 750 seconds across resolver and tool workflow. Limits are
cooperative; in-flight dependency calls are not forcibly cancelled.

## Verification and limits

Run the local two-turn scenario (with the sample corpus ingested and Ollama
running):

```bash
.venv/bin/python -m app.evaluation.session_runner \
  --output evals/results/stage6-followup.json
```

The report contains no session token; the temporary session is deleted after
the run. Its five recorded checks passed: incident-runbook citation on turn
one, payments-platform reference resolution, ownership-guide citation on
turn two, two persisted turns, and a fresh tool search for the follow-up.
This is a small local behavior check, not a general conversational-quality
gate. Unit and PostgreSQL integration tests cover token/scope isolation,
concurrent writes, reset/deletion, retention, expiry, source-title
reauthorization, and controlled errors. Stage 7 now adds semantic evidence
checking and correction; Stage 8 needs real identity, authorization, and
sensitive-data policy; Stage 9 needs scheduled cleanup and operations.
