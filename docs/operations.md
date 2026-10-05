# Local operations guide

This guide runs the API and PostgreSQL in Docker Compose while using Ollama on
the host. It is a reproducible local setup, not a cloud deployment recipe.
Complete IdP, TLS/ingress, secret-manager, distributed throttling, and capacity
configuration for the selected production environment before deployment.

## Prerequisites and startup

Install Docker Compose, `uv`, Python 3.14, and Ollama. Configure a development
password and the issuer, audience, and HTTPS JWKS endpoint in `.env`; never
commit this file. The identity provider must issue RS256 `at+jwt` access tokens
with configured tenant, group, and role claims. Protected API routes fail
closed until auth is configured.

```bash
uv sync --frozen --all-groups
cp .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env`, start Ollama on the host, and download the
models from the README. For containers, `OLLAMA_HOST_CONTAINER` defaults to
`http://host.docker.internal:11434`; set it to the reachable Ollama URL for
your host/network. Host-run API processes use `OLLAMA_HOST` (default
`http://127.0.0.1:11434`).

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f migrate app
```

The migration job waits for PostgreSQL health and must complete successfully
before the API starts. The API container runs as an unprivileged user. Compose
binds ports 5433 and 8000 to loopback; `/health/liveness` is a public process
check. `/health/readiness` checks PostgreSQL and required Ollama models and
requires bearer authentication. `/metrics` is also authenticated; Prometheus
must send `Authorization: Bearer …`. Do not put that bearer token into a URL or
scrape logs. The JSON logs include a validated request ID, route template,
method, status, and elapsed time. They omit request and document bodies.

For host development without building the API container, run
`docker compose up -d db`, then `uv run python -m app.db.migrations`, then
`uv run uvicorn app.main:app --reload`. Keep `.env`'s `POSTGRES_PORT=5433` and
host `OLLAMA_HOST` for this path.

## Database migrations and rollback

`python -m app.db.migrations` serializes migrators with a PostgreSQL advisory
lock, applies each SQL file and its `schema_migrations` checksum row in one
transaction, rejects edits to already-applied files, and skips known versions.
On an empty database it creates the current schema as a baseline and records
the checked migration versions. On an existing database it applies the
ordered Stage 1, 2, 6, and 8 upgrade files. Keep applied SQL files immutable;
add a new migration file and registry entry for future changes.

Migrations are forward-only. A failed SQL migration rolls its file and ledger
entry back together; the integration test exercises this case. There are no
automatic reverse migrations. Before upgrades, take a backup and test the
upgrade on a recent restore. To recover from an incompatible migration, deploy
a compatible application version if the schema permits it, or restore the
backup into a new database and switch the configured database after verifying
it. Keep the original database intact until the restored instance is checked.

## Backup and restore check

Backups use PostgreSQL's custom archive format. The helper refuses to overwrite
an existing output and validates the archive before publishing it. Backups may
contain sensitive source documents; store them encrypted, access-control them,
and apply your retention policy.

```bash
bash scripts/backup_database.sh /secure/location/knowledge-agent.dump
docker compose exec -T db createdb -U knowledge_agent knowledge_agent_restore_check
bash scripts/restore_database.sh \
  /secure/location/knowledge-agent.dump knowledge_agent_restore_check
docker compose exec -T db psql -v ON_ERROR_STOP=1 \
  -U knowledge_agent -d knowledge_agent_restore_check \
  -c "SELECT to_regclass('documents'), to_regclass('conversation_sessions')"
```

The restore helper requires a new, empty database and refuses the configured
source database. After inspection, remove the temporary check database with
`docker compose exec -T db dropdb -U knowledge_agent knowledge_agent_restore_check`.
Keep an untouched copy of the archive and source database until recovery is
confirmed. The CI job runs this backup/restore path against its disposable DB.

## Limits, shutdown, and recovery

The app health check uses the public liveness endpoint. Container shutdown
allows 30 seconds for graceful request completion and the FastAPI lifespan
closes the model client, database pool, and reranker. The per-process
concurrency cap returns HTTP 429 with `Retry-After`; per-identity request rate
limits are also process-local. They do not coordinate multiple workers or
replicas. PostgreSQL and Ollama have independent capacity and failure modes.

For a dependency outage, check `docker compose ps`, app/migration logs, the
authenticated readiness result, PostgreSQL health, Ollama reachability and
model names. Restart only after fixing the dependency. Do not remove the
PostgreSQL volume as a recovery step. For suspected database damage, preserve
the volume and logs, take a copy if possible, restore a known-good archive to
a separate database, verify document and session tables, then switch traffic.
This repository has no automated cloud failover, backup scheduling, or
multi-replica metrics aggregation.

## End-to-end demonstrations

The recorded local demonstrations are reproducible when the sample corpus,
Ollama models, and PostgreSQL are available:

```bash
.venv/bin/python -m app.evaluation.security_runner \
  --output /private/tmp/stage9-security.json
.venv/bin/python -m app.evaluation.session_runner \
  --output /private/tmp/stage9-memory.json
.venv/bin/python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --tools --output /private/tmp/stage9-correction.json
.venv/bin/pytest -q tests/integration
```

Together these check ingestion/storage and scoped retrieval through the
integration suite, multi-document tool search, cited synthesis, memory
follow-up, evidence correction, and an adversarial access/guardrail scenario.
The security replay currently observes that the model follows a directive in
a synthetic legacy document, while citation validation blocks the specific
uncited output. This is a regression demonstration, not a security guarantee.
Use the held-out answer and retrieval commands in `README.md` after changing
models, prompts, or retrieval settings.
