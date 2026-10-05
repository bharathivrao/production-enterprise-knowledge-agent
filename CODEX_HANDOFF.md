# Codex handoff — production enterprise knowledge agent

Updated: 2026-10-05 (America/Toronto)

## Objective and owner constraints

Build the nine-stage enterprise knowledge agent described in
`PROJECT_ROADMAP.md`: ingest enterprise documents, retrieve authorized
evidence, answer with citations, plan and use read-only tools, maintain scoped
memory, verify answers, enforce access/safety controls, and package/operate the
service. The user requested Stage 9 items 1–6 only. Do not start Stage 9 item 7
(deployment to a selected target) until the user chooses/requests it. Work one
stage at a time, explain the function and rationale, then ask the user to
review. Do not commit or push unless explicitly asked. Never commit `.env` or
real credentials. Preserve user data and the existing PostgreSQL volume.

## Current architecture

- Python 3.14, FastAPI/Pydantic; `app/main.py` sets up lifespan, request IDs,
  request metrics, routes, and health endpoints.
- PostgreSQL 17 with pgvector and psycopg pooling. `app/db/migrations.py`
  applies ordered, checksum-verified SQL migrations under an advisory lock.
- PDF/TXT/Markdown/DOCX ingestion; Ollama `embeddinggemma` embeddings and
  `qwen3:4b` generation; SQL-scoped vector/full-text retrieval, hybrid fusion,
  optional reranking, citation validation.
- `/ask/planned` and `/ask/tools` provide bounded plans/read-only tools; local
  stdio MCP exposes the same tool boundary. Sessions persist bounded recent
  user turns and require both a capability token and verified owner. Evidence
  checking supports one bounded correction attempt.
- RS256 access-token validation derives subject/tenant/group scope. PII and
  injection screening, role checks, and per-process rate/concurrency limits
  are application-level controls, not a complete security boundary.
- Stage 9 local packaging: non-root Docker image, Compose PostgreSQL/migration/
  API services, host Ollama connectivity, JSON logs, authenticated Prometheus
  metrics, GitHub Actions CI, backup/restore helpers, and operations docs.

## Important implementation decisions

- Compose project name is exactly `production-enterprise-knowledge-agent`.
  The current DB container was inspected read-only; its existing volume is
  `production-enterprise-knowledge-agent-_postgres_data`. Compose explicitly
  pins that volume name so correcting the project name does not create a new
  empty DB volume. Do not remove or rename this volume.
- Container image resolves CPU-only PyTorch on Linux to avoid pulling the much
  larger CUDA/NVIDIA dependency set. PyTorch CPU index/source is configured in
  `pyproject.toml` and locked in `uv.lock`.
- Migrations are immutable and forward-only. SQL and ledger checksum commit in
  one transaction; fresh DBs create current schema baseline; failed changes
  roll back. No automatic down migrations: backup first and recover by
  forward-fix or restore to a separate DB, verify, then switch.
- Observability is content-safe: logs use static message templates and
  allowlisted metadata; request IDs are validated; route templates and bounded
  metric labels avoid high cardinality. `/metrics` requires authentication.
- CI runs focused Ruff F checks (not wholesale legacy style reformatting),
  frozen dependency audit, unit/API and PostgreSQL integration tests, Docker
  build, and backup/restore against an isolated disposable DB. The hosted
  GitHub Actions workflow has not yet been run/verified in this handoff.
- No production target was selected; TLS/ingress, real IdP verification,
  external secret manager, distributed throttling, sizing, and backup
  scheduling remain target-specific.

## Completed functionality and current state

Stage 9 items 1–6 have been implemented in the working tree, not committed or
pushed. The repo is intended to remain user-reviewable. Stage 9 item 7 is not
started. Other uncommitted changes may be present from Stage 9; inspect `git
status` before editing.

Implemented: Dockerfile and `.dockerignore`; Compose DB/migration/API order;
Ollama host configuration; versioned migration registry/runner and isolated
schema tests; JSON request/security logs, request IDs, request and workflow
metrics; CI checks; guarded custom-format DB backup/restore scripts; updated
README, roadmap, architecture and operations docs; Stage 9 unit/integration
tests. Workflow trace instrumentation is compatible with both typed workflow
results and dictionary test doubles.

Stage 9 demonstration scenarios are documented and point to existing local
evaluation scripts/results: document ingestion/PG integration, planned and
tool-based multi-document answers, session follow-up, correction, and
adversarial guardrail rejection. The model has followed a synthetic embedded
directive in a prior test; citation validation blocked that particular
uncited output. This is not proof of prompt-injection resistance.

## Files changed for Stage 9

- Packaging/config: `Dockerfile`, `.dockerignore`, `docker-compose.yml`,
  `.env.example`, `.gitignore`, `pyproject.toml`, `uv.lock`.
- Migrations/observability: `app/db/migrations.py`, `app/observability.py`,
  `app/main.py`, `app/api/query.py`, `app/api/sessions.py`,
  `app/guardrails/auth.py`, `app/core/config.py`, `app/core/model_client.py`.
- Recovery/CI/docs: `scripts/backup_database.sh`,
  `scripts/restore_database.sh`, `.github/workflows/ci.yml`,
  `docs/architecture.md`, `docs/operations.md`, `README.md`,
  `PROJECT_ROADMAP.md`, this file.
- Tests and small fixes: `tests/test_observability.py`,
  `tests/integration/test_migrations.py`, `tests/test_stage5_tools.py`,
  `tests/test_stage6_memory.py`, `app/evaluation/runner.py`.

## Tests and commands

Verified locally:

- `.venv/bin/pytest -q`: **148 passed, 5 skipped**.
- `env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration`:
  **9 passed** when run with permission to access the local PostgreSQL network.
  A sandbox-restricted run failed to connect to `127.0.0.1:5433`; rerunning
  with local DB network access passed.
- `.venv/bin/ruff check --select F app tests`: passed.
- `POSTGRES_PASSWORD=validation-secret docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Docker image build and import/liveness dependency smoke test passed earlier
  in this Stage 9 work; `uv audit --frozen --preview-features audit` also
  passed with no known vulnerability/adverse status in 117 packages.
- CI workflow is configured but no hosted Actions run result is available.

Useful commands from repo root:

```bash
uv sync --frozen --all-groups
cp .env.example .env   # set POSTGRES_PASSWORD and auth IdP settings
docker compose up -d --build
docker compose ps
docker compose logs -f migrate app
uv run pytest -q
uv run ruff check --select F app tests
env RUN_POSTGRES_INTEGRATION=1 uv run pytest -q tests/integration
uv audit --frozen --preview-features audit
docker build --tag knowledge-agent:local .
```

Host-run API alternative: `docker compose up -d db`, then
`uv run python -m app.db.migrations`, then
`uv run uvicorn app.main:app --reload`. Ollama must be available at
`OLLAMA_HOST` for host execution or `OLLAMA_HOST_CONTAINER` in Compose.
Configured models: `embeddinggemma`, `qwen3:4b` (README also lists
`gemma4:e4b` for the workflows that use it).

Backup/restore commands are documented in `docs/operations.md`. Always use a
new restore target database; do not restore over the source DB. Backups contain
sensitive documents and need encryption/access control/retention.

## Known issues and limitations

- Not deployed. No production IdP, TLS/ingress, secret manager, external
  Prometheus, distributed rate/concurrency control, capacity testing, or
  scheduled backup configuration exists.
- No realistic load/shutdown/fault-injection test has been completed; CI checks
  only local integration, image build, and disposable DB restore behavior.
- The migration runner is forward-only; rollback means restore/forward-fix.
- Rate/concurrency limits are per process; multiple replicas do not coordinate.
- Model/Ollama and workflow deadlines are cooperative; no hard cancellation.
- Heuristic PII/injection screening is incomplete; valid-looking cited attacks
  and subtle secrets may pass.
- Small evaluation corpus and automated graders cannot establish broad quality.
- Existing DB is not migrated or Compose-started as part of this Stage 9 work;
  only its attached volume name was inspected. Integration tests use isolated
  schemas.
- Optional-dependency audit and local tests pass, but hosted CI remains
  unverified. Ruff is deliberately limited to `F` to avoid broad unrelated
  lint churn.

## Remaining work and exact recommended next task

Remaining within future production completion: select a deployment target;
configure that target's TLS/ingress, IdP, secret manager, monitoring, and
distributed throttles; run realistic load and failure/shutdown exercises;
verify backup schedule and restore procedure; execute hosted CI; conduct human
security/quality review. These are not part of current Stage 9 items 1–6.

**Exact next task:** Review the Stage 9 items 1–6 changes and their local test
results with the user. Do not start deployment item 7, commit, or push until
the user explicitly requests it. If review approves continuing, ask which
hosting target to deploy to before making deployment-specific changes.
