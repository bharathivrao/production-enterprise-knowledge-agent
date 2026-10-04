# Production Enterprise Knowledge Agent

A production-oriented knowledge agent that ingests enterprise documents, finds permission-scoped evidence, and answers questions with citations. The project is being built in nine stages, from a transparent RAG pipeline to planning, tools, memory, self-correction, guardrails, and operational deployment.

**Current status:** Stages 1–3 are implemented and pending owner review. Stage 3's held-out evaluation gates pass; on the 15-case test split, answer quality, claim-citation support, answer behavior, and citation-source accuracy each scored 1.0. These are small-corpus local results, not a production-quality guarantee. Stages 4–9 remain planned. See [PROJECT_ROADMAP.md](PROJECT_ROADMAP.md) for the detailed production checklist and [CODEX_HANDOFF.md](CODEX_HANDOFF.md) for the latest implementation and evaluation handoff.

## Original project stages

| Stage | Focus | Status |
|---|---|---|
| 1 | Basic RAG: ingestion, vector storage, retrieval, cited answers | Implemented |
| 2 | Production retrieval: hybrid search and reranking | Implemented; vector is the measured default |
| 3 | Evaluation: datasets, metrics, quality gates | Implemented; all acceptance gates pass; pending owner review |
| 4 | Goal analysis and planning | Planned |
| 5 | Tools and MCP | Planned |
| 6 | Working and conversation memory | Planned |
| 7 | Self-correction and evidence verification | Planned |
| 8 | Guardrails and enterprise access controls | Planned |
| 9 | Packaging, deployment, and operations | Planned |

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

**Planned:** Turn complex requests into typed objectives, entities, constraints, deliverables, and bounded substeps. Ask for clarification when required information is missing. Execute plans with limits on steps, model calls, tokens, and time.

**Target demonstration:** Compare retry and dead-letter-queue handling across multiple systems, cite each finding, and identify gaps without making unsupported claims.

### Stage 5 — Tools

**Planned:** Give the agent a small allowlist of typed, read-only tools, initially document search and document reading. Validate tool arguments, enforce permissions, limit calls, and return controlled errors. Add MCP integration where it supports the project goals.

**Target demonstration:** The agent selects an appropriate search tool, uses its result as evidence, and handles invalid arguments or tool failure safely.

### Stage 6 — Memory

**Planned:** Keep bounded working state for a plan and its evidence, plus isolated conversation history for follow-up questions. Define storage, retention, expiration, and deletion. Preserve provenance so previous model answers are not mistaken for verified evidence.

**Target demonstration:** A follow-up resolves references from the same session without leaking context across users or sessions.

### Stage 7 — Self-correction

**Planned:** Check whether claims have supporting evidence, detect missing coverage or conflicting sources, then revise the plan or search a bounded number of times. Preserve citations through revisions and abstain when evidence remains weak.

**Target demonstration:** A weak first retrieval triggers one useful additional search or a clear abstention, without an unbounded agent loop.

### Stage 8 — Guardrails

**Built so far:** Request validation, upload limits, evidence-as-data instructions, citation ID validation, and controlled model dependency errors.

**Planned:** Authentication and authorization; tenant and document access enforcement across ingestion, retrieval, tools, memory, and citations; prompt-injection testing; sensitive-data and logging policies; rate and resource limits; and audit behavior.

**Target demonstration:** A user cannot retrieve another user's documents, malicious document text cannot override system instructions, and unsupported claims produce an abstention or a clearly qualified answer. Prompt wording alone is not an access-control boundary.

### Stage 9 — Packaging and operations

**Planned:** Reproducible application/database setup, CI checks, migrations and recovery procedures, structured logs/tracing/metrics, deployment security, and operational runbooks.

## Production completion work

Stages 1–8 describe the learning and feature milestones; Stage 9 covers production packaging and operations. Remaining production work includes:

- Review and accept completed Stage 3; continue growing the evaluation dataset beyond its initial 50 cases without leaking held-out examples.
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
```

Stages 4–7 extend this foundation with planning, tools, memory, and bounded evidence checks. Stage 8 applies access and safety controls across the workflow.

## Technology

- Python 3.14, FastAPI, Pydantic
- PostgreSQL 17 with pgvector, psycopg
- Ollama: `embeddinggemma` for embeddings, `qwen3:4b` for answers
- PostgreSQL full-text search, reciprocal rank fusion
- Sentence Transformers cross-encoder for optional reranking
- PyMuPDF, python-docx, tiktoken
- Docker Compose and pytest

## Run locally

Prerequisites: Python 3.14, [uv](https://docs.astral.sh/uv/), Docker, and Ollama.

1. Install dependencies and make a local environment file:

   ```bash
   uv sync --all-groups
   cp .env.example .env
   ```

   Set `POSTGRES_PASSWORD` in `.env` to a local development password.

2. Start PostgreSQL/pgvector:

   ```bash
   docker compose up -d db
   ```

3. Pull the configured Ollama models:

   ```bash
   ollama pull embeddinggemma
   ollama pull qwen3:4b
   ollama pull gemma4:e4b
   ```

   Keep Ollama running and reachable from the application.

4. Start the API:

   ```bash
   uv run uvicorn app.main:app --reload
   ```

   Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for the interactive API.

5. Run unit/API tests:

   ```bash
   uv run pytest -q
   ```

   PostgreSQL integration tests are opt-in and require the local database:

   ```bash
   RUN_POSTGRES_INTEGRATION=1 uv run pytest -q tests/integration
   ```

Configuration is documented in [.env.example](.env.example). Do not commit a real `.env`.

## API overview

- `GET /health` and `GET /health/liveness`: service health endpoints.
- `POST /documents`: upload a PDF, TXT, Markdown, or DOCX document.
- `POST /search`: retrieve evidence without answer generation.
- `POST /ask`: answer from retrieved evidence with citations or abstain.

Use the OpenAPI page at `/docs` for request schemas and response examples. Available retrieval settings and filters are defined by the API request model.

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

Additional commands for grader calibration and repeated-run checks are in [evaluation policy](docs/evaluation-policy.md). The current held-out answer gate is known to fail; inspect the report and handoff before treating it as a release check.

## Project documents

- [Detailed status and production checklist](PROJECT_ROADMAP.md)
- [Current engineering handoff and exact next task](CODEX_HANDOFF.md)
- [Ingestion and provenance policy](docs/ingestion-policy.md)
- [Retrieval and reranking measurements](docs/retrieval-policy.md)
- [Evaluation methodology and split discipline](docs/evaluation-policy.md)

## Scope and limitations

This is an in-progress learning and portfolio project. It is not certified or approved for real enterprise data. Before production use, complete and review authentication, tenant/document authorization, security controls, deployment hardening, load testing, data retention/deletion policy, and operational recovery. Stage 3's gates pass on the current small local dataset; they do not establish production readiness.
