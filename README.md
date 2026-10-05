# Production Enterprise Knowledge Agent

A production-oriented knowledge agent that ingests enterprise documents, finds permission-scoped evidence, and answers questions with citations. The project is being built in nine stages, from a transparent RAG pipeline to planning, tools, memory, self-correction, guardrails, and operational deployment.

**Current status:** Stages 1–8 are implemented. Stage 8 adds signed-token authentication, tenant/group authorization, session ownership, and guardrail checks. The small-corpus quality and local security tests are not a production guarantee; Stage 9 operations and deployment remain. See [PROJECT_ROADMAP.md](PROJECT_ROADMAP.md), [security policy](docs/security-policy.md), and [CODEX_HANDOFF.md](CODEX_HANDOFF.md).

## Original project stages

| Stage | Focus | Status |
|---|---|---|
| 1 | Basic RAG: ingestion, vector storage, retrieval, cited answers | Implemented |
| 2 | Production retrieval: hybrid search and reranking | Implemented; vector is the measured default |
| 3 | Evaluation: datasets, metrics, quality gates | Implemented; all acceptance gates pass |
| 4 | Goal analysis and planning | Implemented |
| 5 | Tools and MCP | Implemented |
| 6 | Working and conversation memory | Implemented |
| 7 | Self-correction and evidence verification | Implemented |
| 8 | Guardrails and enterprise access controls | Implemented; deployment integration remains |
| 9 | Packaging, deployment, and operations | Local packaging, migrations, observability, CI, and recovery workflow implemented; deployment remains |

## Stage details

### Stage 1 — Basic RAG

**Built:** FastAPI endpoints for document ingestion, search, and question answering; PDF, UTF-8 TXT, Markdown, and DOCX parsing; configurable token chunking; local Ollama embeddings; PostgreSQL/pgvector persistence; duplicate detection; vector search; context construction; evidence-grounded answers; citation ID validation; abstention when evidence is insufficient.

**Key learning:** Understand each step that turns a document into retrievable evidence before adding agent frameworks.

### Stage 2 — Production retrieval

**Built:** PostgreSQL full-text search, vector search, hybrid rank fusion, an optional cross-encoder reranker, scope filters, duplicate and document-version handling, and bounded context construction.

**Measured decision:** Vector search remains the default. In the Stage 2 benchmark, vector and hybrid tied on MRR@3; reranking added latency without improving that benchmark. See [retrieval policy](docs/retrieval-policy.md) for measurements and limits.

**Key learning:** Combine retrieval methods only when evaluations show an improvement.

### Stage 3 — Evaluation

**Built:** A versioned 50-case dataset with development and held-out test splits; retrieval and answer evaluation; source coverage, answer quality, latency, and token metrics; grader calibration; repeatability checks; and acceptance gates. The answer contract distinguishes grounded answers, abstentions, and clarification requests. Prompt v3.1.0 asks for minimal direct citations and clarification when the user's goal or situation is underspecified.

**Measured result:** The held-out answer report completed 15/15 cases with no runner failures. Correctness, completeness, faithfulness, relevance, claim citation support, abstention/clarification behavior, and citation-source accuracy each scored 1.0. Retrieval and grader-calibration acceptance gates also pass. The 35-case development answer gate passes with citation-source accuracy 0.971. Automated grading is an estimate and should be sampled by a human.

**Key learning:** Measure retrieval and answer quality separately, keep held-out cases for acceptance, and investigate failures rather than optimizing only one aggregate score.

### Stage 4 — Goal analysis and planning

**Built:** `POST /ask/planned` and a CLI turn complex requests into typed objectives, entities, constraints, deliverables, and at most three read-only search steps followed by server-owned synthesis. The workflow asks for clarification when intent is too vague, validates model-produced queries and source IDs, and returns a state trace, citations, and usage. The existing `/ask` remains the single-pass path.

**Measured demonstration:** A local three-document comparison cited the payment incident runbook, service ownership guide, and current retry policy in about 9.3 seconds, using six model calls and 1,287 accounted tokens. A vague request returned clarification without searching. See [planning policy](docs/planning-policy.md) and the saved `evals/results/stage4-*.json` reports. These examples are not a broad quality benchmark; runtime enforcement is cooperative rather than hard cancellation.

**Key learning:** Keep the model's role narrow: it proposes focused queries and evidence-grounded findings, while the server fixes permitted steps, budgets, scope, and citation validation.

### Stage 5 — Tools

**Built:** `POST /ask/tools` routes bounded search through a typed dispatcher, lets the model choose up to three numbered scoped search results, maps those numbers to chunk IDs server-side, then reads and synthesizes cited findings. The only tools are `search_documents` and `read_document_chunks`. Both validate arguments and preserve the server's document scope. The local stdio MCP server exposes the same dispatcher, with no network listener or write tools. See [tool policy](docs/tool-policy.md).

**Measured demonstration:** A local two-document run selected and read evidence from both named documents and cited each. A three-document run read three sources but cited only two in the final answer; source suitability remains an evidence-checking limitation. Invalid arguments, unknown tools, dependency failure, and unauthorized chunk reads return controlled errors. This is not an authenticated enterprise service.

**Why this design:** Search returns short previews; full chunk text becomes answer evidence only after a scoped read. The model selects numbered candidates, while the server owns their IDs, the tool allowlist, argument validation, access scope, and budgets. The default tool workflow allows up to three searches, one read of up to three chunks, and synthesis; see [tool policy](docs/tool-policy.md) for exact limits and failure behavior.

### Stage 6 — Memory

**Built:** Capability-protected PostgreSQL sessions, bounded per-request working state, recent-turn selection, structured follow-up resolution, expiry, reset, and deletion. A follow-up uses prior user questions and currently visible source titles to resolve references, then searches and reads evidence again under the current server scope. Prior generated answers are stored for display but never sent to the resolver as facts. See [memory policy](docs/memory-policy.md).

**Measured demonstration:** A local two-turn run answered a severity-one payment incident question from the incident runbook, resolved “Who owns that service?” to the payments platform, ran a fresh tool search, and cited the ownership guide. All five scenario checks passed. PostgreSQL tests cover wrong-token and wrong-tenant isolation, concurrent writes, retention, expiry, reset, deletion, and source-title reauthorization.

**Important limit:** The session token is a separate opaque capability, not a user identity. Stage 8 binds sessions to a verified subject and tenant/scope as well; the capability must still be protected.

### Stage 7 — Self-correction

**Built:** Planned, tool-assisted, and session answers now pass through a structured support/contradiction/coverage checker after structural citation validation. An explicitly requested document must support its corresponding finding when its name resolves uniquely. One targeted, non-repeated correction search and revision are allowed. A second check keeps only supported findings; an unavailable checker fails closed. The single-pass `/ask` path remains unchanged. See [verification policy](docs/verification-policy.md).

**Measured demonstration:** The prior three-source tool run cited only two named documents. A Stage 7 local replay used one correction search and cited all three requested documents in the final answer. It took about 25.4 seconds and 11 model calls versus 13.7 seconds and 7 calls for the prior run. This is one case, not a broad accuracy claim; the checker can still make mistakes.

### Stage 8 — Guardrails

**Built:** Provider-neutral RS256 JWT access-token validation against configured issuer, audience, and HTTPS JWKS; identity-derived tenant/group/subject scope; private-by-default uploads and role-gated sharing/management; subject-bound sessions; scoped deduplication; recognizable secret/high-risk PII and document-instruction rejection; per-process rate and concurrency gates; and metadata-only security audit events. See [security policy](docs/security-policy.md) for the precise contract and limitations.

**Adversarial result:** A synthetic legacy document's embedded directive did influence the local model, but citation validation rejected the uncited result before `/ask` could deliver it. Cross-group retrieval returned no fixture document. This does **not** prove robust prompt-injection resistance; subtler cited attacks and broader DLP remain open risks.

### Stage 9 — Packaging and operations

**Built:** A non-root API image and Compose stack for PostgreSQL, ordered migrations, and the API; explicit host Ollama connectivity; a checksum-tracked transactional migration runner; JSON request logs, request IDs, and authenticated Prometheus metrics; GitHub Actions lint/test/integration/image-build checks; and guarded backup/restore helpers. See the [architecture overview](docs/architecture.md) and [operations guide](docs/operations.md).

**Still deployment-specific:** TLS/ingress, an actual identity-provider integration, secret-manager wiring, distributed rate/concurrency limits, production capacity sizing, and monitored backup scheduling depend on the selected hosting target.

## Production completion work

Stages 1–8 describe the learning and feature milestones; Stage 9 covers production packaging and operations. Remaining production work includes:

- Continue growing the evaluation dataset beyond its initial 50 cases without leaking held-out examples.
- Add CI for tests and evaluation gates; document migrations and rollback.
- Finish the application container, deployment configuration, secrets handling, structured logs, request tracing, metrics, readiness probes, backups, and recovery procedures.
- Test realistic load, failure recovery, and access-control boundaries.
- Publish setup instructions, operational guidance, evaluation results, and known limitations.

A green small-corpus score is useful evidence, but it does not by itself establish production readiness.

## Architecture

```text
Documents
   │
   ▼
Parse → Chunk → Embed → PostgreSQL + pgvector
                             │
Question ───────────────────┤
                             ▼
           Scoped vector / full-text retrieval
                             │
                     Hybrid fusion / rerank
                             │
                      Bounded evidence context
                             │
                             ▼
                 Answer with citations or abstain

Complex question → Typed goal → Validated search plan → Scoped search tool
                                               │
                                               ▼
                                  Selected scoped read → Cited synthesis
                                                        │
                                                        ▼
                                          Evidence check → Return or one correction

Session token + recent user turns → Follow-up resolver → Fresh scoped workflow
```

Stages 4–7 add planning, read-only tools, sessions, and evidence correction. Stage 8 derives the tenant/group scope from a verified bearer identity before the API enters these workflows; the session capability is additionally bound to the verified subject.

## Technology

- Python 3.14, FastAPI, Pydantic
- PostgreSQL 17 with pgvector, psycopg
- Ollama: `embeddinggemma` for embeddings, `qwen3:4b` for answers
- PostgreSQL full-text search, reciprocal rank fusion
- Sentence Transformers cross-encoder for optional reranking
- PyMuPDF, python-docx, tiktoken
- Official Python MCP SDK for the local stdio tool adapter
- PyJWT with cryptography for RS256 access-token validation
- Prometheus client metrics
- Docker Compose and pytest

## Run locally

Prerequisites: Python 3.14, [uv](https://docs.astral.sh/uv/), Docker Compose, and Ollama.

1. Install dependencies and make a local environment file:

   ```bash
   uv sync --all-groups
   cp .env.example .env
   ```

   Set `POSTGRES_PASSWORD` in `.env` to a local development password. Set
   `AUTH_ISSUER`, `AUTH_AUDIENCE`, and HTTPS `AUTH_JWKS_URL` for an identity
   provider that issues `at+jwt` RS256 access tokens with `tenant_id`, `groups`,
   and `roles` claims. Protected endpoints fail closed without this setup.

2. Pull the configured Ollama models and keep Ollama reachable from Docker. On Docker Desktop the default container URL is `http://host.docker.internal:11434`; configure `OLLAMA_HOST_CONTAINER` in `.env` on other hosts.

   ```bash
   ollama pull embeddinggemma
   ollama pull qwen3:4b
   ollama pull gemma4:e4b
   ```

3. Build and start PostgreSQL/pgvector, apply migrations, and start the API:

   ```bash
   docker compose up -d --build
   ```

   Compose waits for PostgreSQL and the one-shot migration job before starting the API. The API and database ports bind to loopback.

4. For host-run development instead, start only the database and run the API locally:

   ```bash
   docker compose up -d db
   uv run python -m app.db.migrations
   uv run uvicorn app.main:app --reload
   ```

   Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the interactive API.

5. Run checks:

   ```bash
   uv run ruff check --select F app tests
   uv run pytest -q
   ```

   PostgreSQL migrations and integration tests require a running database:

   ```bash
   env RUN_POSTGRES_INTEGRATION=1 uv run pytest -q tests/integration
   ```

   CI also builds the app image and exercises a backup/restore into a separate disposable database. See the [operations guide](docs/operations.md).

Configuration is documented in [.env.example](.env.example). Do not commit a real `.env`. Existing databases are upgraded by the Compose migration job before API startup; see [migration and restore behavior](docs/operations.md#database-migrations-and-rollback).

## API overview

- `GET /health` and `GET /health/liveness`: public shallow service health endpoints. `GET /health/readiness` requires a bearer token.
- `GET /metrics`: authenticated Prometheus metrics. Send the same `Authorization: Bearer <access token>` header used for API requests.
- `POST /documents`: upload a PDF, TXT, Markdown, or DOCX document. Requires `document:write`; private to the signed subject by default. Multipart `access_groups` can share to verified groups, with `document:publish` required for `public`.
- `POST /search`: retrieve evidence without answer generation.
- `POST /ask`: answer from retrieved evidence with citations or abstain.
- `POST /ask/planned`: analyze a goal, run a bounded read-only search plan, and return cited findings or a clarification. Body: `{"query":"...","top_k":3}`; response includes `state`, `answer`, `citations`, `goal`, `plan`, `trace`, `usage`, and `metadata`.
- `POST /ask/tools`: use the validated read-only search and chunk-reading tools for the same bounded answer workflow. The body is `{"query":"...","top_k":3}`; caller-supplied scope is rejected.
- `POST /sessions`: create an expiring, subject-bound session; returns its ID and a one-time capability token.
- `POST /sessions/{session_id}/ask`: answer a follow-up with `X-Session-Token` and `{"query":"...","top_k":3}`.
- `GET /sessions/{session_id}`, `POST /sessions/{session_id}/reset`, and `DELETE /sessions/{session_id}`: inspect, clear, or delete that session with the same token.

All document/query/session routes require `Authorization: Bearer <access token>` from the configured IdP. Document replace/reindex/delete additionally require `document:manage`; session routes also require `X-Session-Token`. Use the OpenAPI page at `/docs` for request schemas and response examples.

For example, after ingesting the sample corpus:

```bash
curl -sS -X POST http://127.0.0.1:8000/ask/tools \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"Compare the payment incident runbook and service ownership guide: who responds to a severity-one payment incident and who owns the payments platform?","top_k":3}'
```

The response includes the cited answer, goal, plan, redacted tool-state trace,
usage, and model/limit metadata. An underspecified question can return a
clarification without calling tools.

## Evaluation commands

Use the development split for iteration:

```bash
uv run python -m app.evaluation.runner --retriever vector --top-k 3 \
  --split development --output evals/results/retrieval-development.json
uv run python -m app.evaluation.answer_runner --split development --top-k 3 \
  --output evals/results/answers-development.json
```

Run held-out acceptance only after choices are fixed:

```bash
uv run python -m app.evaluation.runner --retriever vector --top-k 3 \
  --split test --output evals/results/retrieval-test.json
uv run python -m app.evaluation.answer_runner --split test --top-k 3 \
  --output evals/results/answers-test.json
uv run python -m app.evaluation.gates --kind retrieval \
  --report evals/results/retrieval-test.json
uv run python -m app.evaluation.gates --kind answer \
  --report evals/results/answers-test.json
```

Additional commands for grader calibration and repeated-run checks are in [evaluation policy](docs/evaluation-policy.md). The recorded Stage 3 held-out gates pass on the small local dataset; they are not a release certification.

To run the Stage 4 workflow directly against the ingested sample corpus:

```bash
uv run python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --output evals/results/stage4-three-source-comparison.json
```

To reproduce the Stage 5 two-document tool run, use:

```bash
uv run python -m app.agents.workflow \
  "Compare the payment incident runbook and service ownership guide: who responds to a severity-one payment incident and who owns the payments platform?" \
  --tools --output evals/results/stage5-tool-comparison.json
```

The saved three-source and clarification runs are in `evals/results/stage5-*.json`.
These are local examples, not a Stage 5 quality gate; the three-source run
missed one named document in its final citations. The Stage 7 replay is saved
as `evals/results/stage7-three-source-comparison.json`.
The Stage 7 session replay is saved as `evals/results/stage7-session-followup.json`;
all five scenario checks passed and its temporary session was deleted.

To run the Stage 6 two-turn check, use:

```bash
uv run python -m app.evaluation.session_runner \
  --output evals/results/stage6-followup.json
```

It creates and deletes a temporary session and does not save its token. Use
`POST /sessions` for an interactive session and keep the returned token private.

## Local MCP server

A trusted local MCP client can launch the read-only server from the repository
root using:

```bash
uv run python -m app.tools.mcp_server
```

This is a stdio protocol process, not an interactive shell or HTTP service;
it waits for a client to send MCP messages. It exposes only `search_documents`
and `read_document_chunks`, both backed by the same validated dispatcher as
`/ask/tools`. Its scope is fixed to public documents. Do not expose it over a
network or use it for private enterprise data; user authentication and
delegated tenant access are not implemented yet.

## Project documents

- [Detailed status and production checklist](PROJECT_ROADMAP.md)
- [Current engineering handoff and exact next task](CODEX_HANDOFF.md)
- [Ingestion and provenance policy](docs/ingestion-policy.md)
- [Retrieval and reranking measurements](docs/retrieval-policy.md)
- [Evaluation methodology and split discipline](docs/evaluation-policy.md)
- [Stage 4 planning policy and measured examples](docs/planning-policy.md)
- [Stage 5 tool contracts, MCP boundary, and measured limitations](docs/tool-policy.md)
- [Stage 6 session, retention, and evidence-memory policy](docs/memory-policy.md)
- [Stage 7 evidence checking, correction, and measured tradeoff](docs/verification-policy.md)

## Scope and limitations

This is an in-progress learning and portfolio project. It is not certified or approved for real enterprise data. Before production use, complete and review authentication, tenant/document authorization, security controls, deployment hardening, load testing, data retention/deletion policy, and operational recovery. Session tokens do not replace user authentication. Stage 3's gates pass on the current small local dataset; they do not establish production readiness.
