# Production Enterprise Knowledge Agent — Status and Remaining Roadmap

Updated: October 3, 2026

## Purpose and scope

This document records the implemented system and the work remaining to complete the original enterprise knowledge agent vision. The original plan described eight learning milestones; this roadmap uses the nine-stage structure agreed in the conversation, including service completion and packaging/deployment.

The target system accepts enterprise documents, answers questions with supporting evidence, decomposes complex tasks, uses tools, maintains memory, checks its work, and enforces access and safety policies.

Current status: Stages 1 and 2 are complete: the service has reliable multi-format ingestion plus permission-aware vector, PostgreSQL full-text, hybrid, and cross-encoder-reranked retrieval with measured defaults. It is not yet a complete agent or a production-ready enterprise service.

Status is based on inspected repository code and recorded evaluation results. Empty placeholder files do not count as implemented features. Checklists below are completion targets, not claims that the features already exist.

## What is already built

### Application and configuration

- FastAPI application with document upload, search, answer, root, health, and liveness endpoints.
- Pydantic request validation and structured ingestion/answer responses.
- Central settings loaded from environment configuration, with the database password represented as a SecretStr.
- PostgreSQL with pgvector provisioned through Docker Compose.
- Local Ollama models: embeddinggemma for embeddings and qwen3:4b for answer generation.
- Shared Ollama client with a five-second connection timeout and 120-second network timeout. This is not a total request deadline.

### PDF ingestion and persistence

- PyMuPDF parsing with page metadata.
- Rejection of unreadable, non-PDF, password-protected, empty, and textless PDF content through the implemented validation paths.
- Token-based chunking with configurable chunk size and overlap; current defaults are 500 tokens and 50 overlap.
- Local 768-dimensional embeddings with truncation disabled.
- PostgreSQL document/chunk storage, foreign keys, uniqueness constraints, and dimensionality checks.
- SHA-256 content deduplication, including early reuse and storage-conflict handling.
- Upload response distinguishes newly created documents from reused documents.
- A 10 MiB upload check in the endpoint, plus temporary file cleanup.

### Retrieval and generation

- Vector search using pgvector cosine distance.
- Chunk IDs and source metadata in retrieval results.
- In-memory BM25 ranking, with shared query/document tokenization and common-word filtering.
- Hybrid retrieval using Reciprocal Rank Fusion and chunk-ID deduplication.
- Vector retrieval remains the default for /ask; hybrid has not demonstrated an improvement on the measured dataset.
- Evidence context with source labels such as S1 and S2.
- Evidence-only generation instructions and explicit abstention behavior.
- Cleanup for the observed model output containing a closing </think> delimiter.
- Citation-ID validation: unknown IDs are rejected and returned citations are derived from IDs in the cleaned final answer.

### Reliability and tests

- Controlled API responses for invalid requests/documents and citation validation failures.
- Model connection failure: HTTP 503.
- Model timeout: HTTP 504.
- Ollama response errors: shared HTTP 502 handler.
- Unit and API tests for ingestion, deduplication, retrieval fusion, citation handling, output cleanup, generation pipeline behavior, evaluation, and dependency failure paths.
- User-reported passing tests during implementation. This document does not establish a fresh full-suite test result.

### Evaluation

- Golden dataset with 15 cases: 11 answerable and four unsupported questions.
- Retrieval runner measures Hit@k and Mean Reciprocal Rank, skips unsupported cases, and saves JSON reports with metadata.
- Answer runner records expected/actual answers, citations, abstention behavior, and allowed source-page checks.
- Saved prompt experiments and baseline reports support comparisons.

## Recorded results and their limits

| Evaluation | Recorded result |
|---|---|
| Vector, expanded retrieval dataset | Hit@3: 100% (11/11); MRR@3: 0.9545 |
| Hybrid, expanded retrieval dataset | Hit@3: 100% (11/11); MRR@3: 0.9545 |
| Latest answer evaluation | Abstention checks: 15/15; source-page checks: 15/15 |

These results describe a small development corpus and a dataset used during prompt tuning. They do not establish general production quality.

Citation-ID validation proves that cited IDs exist. The answer evaluator checks that cited document/page pairs are allowed for a case. Neither mechanism verifies that every claim follows from the cited passage or that the answer is complete.

Observed examples demonstrate why this matters: a privacy answer once omitted the instruction to redact; a retry answer lost the qualifier “up to”; an approval answer once inferred authority from investigation responsibility. Later experiments improved several of these behaviors, but factual review remains necessary.

## Nine stages remaining for production completion

### 1. Complete ingestion and service reliability

Status: completed October 3, 2026; pending owner review.

- [x] Support TXT, Markdown, and DOCX throughout parsing, chunking, upload validation, content-type persistence, and citations.
- [x] Preserve meaningful section/source metadata; use nullable page numbers for unpaginated formats.
- [x] Define extraction behavior for DOCX tables, headings, and document order.
- [x] Provide a documented policy for scanned PDFs/OCR and unsupported files.
- [x] Enforce upload limits before excessive request buffering, in addition to endpoint checks.
- [x] Add safe document deletion, replacement, and reindexing workflows.
- [x] Record parser, chunking, embedding model/version, and embedding dimension provenance.
- [x] Reindex when configuration changes rather than treating matching file hashes as proof of equivalent indexed content.
- [x] Resolve legacy documents without hashes and define tenant-scoped deduplication before adding multiple tenants.
- [x] Handle database connectivity failures with controlled responses; configure pooling and appropriate database timeouts.
- [x] Add dependency readiness checks. Existing /health and /health/liveness are shallow checks.
- [x] Manage shared model/database client startup and shutdown.
- [x] Add integration tests against real PostgreSQL/pgvector and representative supported documents.

Completion evidence: supported formats ingest correctly; metadata and deduplication remain consistent; invalid uploads and dependency failures behave predictably.

Evidence: 44 unit/API tests pass; the opt-in integration test ingests and deletes
representative PDF, TXT, Markdown, and DOCX documents against PostgreSQL/pgvector.
The Stage 1 migration was successfully applied to the local development database.

### 2. Production retrieval and reranking

Status: completed October 3, 2026; pending owner review.

- [x] Implement a cross-encoder reranker over retrieved candidates.
- [x] Evaluate vector, BM25, hybrid, and reranked variants using the same corpus and dataset.
- [x] Add questions requiring evidence across multiple documents, including conflicting versions.
- [x] Evaluate chunk-size/overlap choices against the actual embedding model's input limits.
- [x] Add metadata filters and enforce document permissions before retrieval results enter prompts or rerankers.
- [x] Replace per-query full-corpus BM25 rebuilding with a maintained index or PostgreSQL search approach suitable for the expected corpus size.
- [x] Select candidate counts, indexes, and context budgets based on measured quality and latency.
- [x] Define behavior when retrieval finds weak, stale, duplicate, or contradictory evidence.

Completion evidence: reproducible quality/latency comparisons and a documented default retriever justified by results. Hybrid is not automatically considered better.

Evidence: all five Stage 2 comparisons use the same versioned dataset and corpus.
Vector remains the default because vector and hybrid tied for the best MRR@3
(0.9643), while hybrid added no quality and reranking reduced MRR to 0.9286 with
higher latency. All variants achieved complete source coverage at `k=3` on the
14 answerable cases; see `docs/retrieval-policy.md` for limitations.

### 3. Evaluation and quality measurement

Status: retrieval metrics and basic answer checks implemented.

- [ ] Expand to approximately 50 varied questions initially, and eventually 100+.
- [ ] Separate development questions from a held-out test set.
- [ ] Cover multi-document, ambiguous, conflicting, unsupported, and adversarial questions.
- [ ] Score factual correctness, completeness, faithfulness, answer relevance, and claim-level citation support.
- [ ] Add Recall@k/context precision where applicable; do not label the current Hit@k metric as Recall@k.
- [ ] Record latency distributions, token usage, dependency failures, and relevant resource/cost measurements.
- [ ] Version prompts, datasets, corpus snapshots, model identifiers, and retrieval configuration.
- [ ] Add repeatability checks and record variation across runs.
- [ ] Capture per-case exceptions so one failed request does not lose the whole evaluation run.
- [ ] Define explicit acceptance thresholds and CI regression gates.
- [ ] Calibrate automated graders against human review if introducing model-based evaluation.

Completion evidence: a reproducible report distinguishes retrieval failures, unsupported answers, incorrect citations, and incomplete answers.

### 4. Goal analysis and planning

Status: placeholder files only.

- [ ] Define typed goal and plan schemas with objectives, entities, deliverables, constraints, and steps.
- [ ] Decompose complex questions into bounded subqueries.
- [ ] Identify questions requiring clarification instead of guessing missing user intent.
- [ ] Validate model-produced plans and permitted step types.
- [ ] Execute a workflow with explicit states and observable transitions.
- [ ] Bound step count, model calls, tokens, and total runtime.
- [ ] Test comparisons spanning several runbooks or systems.

Completion evidence: a complex question yields a valid plan, executes it within limits, and produces a cited answer.

### 5. Tools and MCP

Status: ordinary search functions exist; agent tool selection/execution is not implemented.

- [ ] Define typed search and document-reading tool interfaces.
- [ ] Add a validated dispatcher for tool selection and arguments.
- [ ] Enforce allowlists, access controls, timeouts, and safe tool-error propagation.
- [ ] Keep the initial tools read-only; require explicit authorization for future state-changing tools.
- [ ] Integrate MCP where required by the original learning scope and verify the server/tool boundary.
- [ ] Capture tool inputs/results in workflow traces with appropriate redaction.
- [ ] Test malformed arguments, unknown tools, tool failures, and unauthorized access.

Completion evidence: the agent selects and uses authorized tools correctly, including controlled failure behavior.

### 6. Working and conversation memory

Status: placeholder files only.

- [ ] Define working memory for plan progress, evidence, tool observations, and unresolved questions.
- [ ] Add conversation sessions with user/tenant isolation.
- [ ] Define persistence, retention, deletion, and expiry behavior; use PostgreSQL or Redis according to requirements.
- [ ] Bound history size and summarize or select context when necessary.
- [ ] Preserve source references and avoid treating previous generated answers as verified evidence.
- [ ] Handle follow-up references and corrections without leaking another session's data.
- [ ] Test concurrent sessions and memory reset/deletion.

Completion evidence: follow-up questions preserve context while evidence grounding and session isolation remain intact.

### 7. Evidence checking and self-correction

Status: citation-ID validation exists; critic and agent loop are not implemented.

- [ ] Implement an evidence checker for missing support, contradictions, and incomplete coverage.
- [ ] Separate structural citation validation from semantic support checking.
- [ ] Search again or revise the plan when evidence is insufficient.
- [ ] Limit retries and prevent repeated identical searches or infinite loops.
- [ ] Carry provenance through revisions and reject invented citations.
- [ ] Abstain or return clearly qualified partial results when attempts are exhausted.
- [ ] Evaluate whether correction improves answers rather than reinforcing errors.

Completion evidence: an initially weak answer is improved through a bounded correction cycle, or the workflow safely abstains.

### 8. Guardrails and enterprise access controls

Status: basic input checks and evidence-as-data prompting exist; dedicated guardrail modules are empty.

- [ ] Add authentication and define user/tenant authorization.
- [ ] Enforce document permissions consistently in ingestion, retrieval, tools, memory, and citations.
- [ ] Make deduplication and document lookup respect the authorization boundary.
- [ ] Test prompt injection in documents, questions, and tool output.
- [ ] Define PII/secrets handling, redaction, logging restrictions, and retention policies.
- [ ] Add rate limits and bounded upload, token, tool, and concurrency budgets.
- [ ] Manage credentials securely and restrict service exposure.
- [ ] Audit accesses and policy decisions without logging sensitive content unnecessarily.
- [ ] Test malicious uploads, unauthorized source references, and cross-session/tenant leakage.

Completion evidence: adversarial and authorization tests pass, and policy decisions are documented. Prompt instructions alone do not establish a security boundary.

### 9. Packaging, observability, deployment, and delivery

Status: database Compose setup exists; README, Dockerfile, and dedicated logging module are empty.

- [ ] Write a Dockerfile and a reproducible application/database setup with explicit Ollama connectivity.
- [ ] Document prerequisites, supported Python version, model downloads, environment settings, and startup commands.
- [ ] Provide an example configuration without real secrets.
- [ ] Add versioned database migrations with a tested upgrade/rollback strategy.
- [ ] Add structured logs, request IDs, workflow traces, and metrics for latency/errors/retries.
- [ ] Set up CI for tests, linting, and appropriate dependency/security checks.
- [ ] Deploy to the selected target with TLS, protected credentials, and readiness probes.
- [ ] Test backups/restores, load limits, graceful shutdown, and operational recovery.
- [ ] Write an architecture overview, API examples, evaluation results, known limitations, and an operations runbook.
- [ ] Demonstrate ingestion, multi-document planning/tool use, memory, correction, abstention, and guardrail rejection end to end.

Completion evidence: another developer can set up and run the project from documentation; the deployed service is observable and recoverable.

## Implementation sequence

1. Finish ingestion, remaining failure tests, and dependency readiness.
2. Implement reranking and build a corpus that requires multi-document retrieval.
3. Strengthen evaluation before changing the default retrieval/generation workflow.
4. Add typed planning and tool execution as one bounded vertical workflow.
5. Add isolated memory and bounded evidence-check/retry behavior.
6. Apply authentication, access controls, and guardrail tests across the complete workflow.
7. Finish packaging, CI, observability, deployment, and the end-to-end demonstration.

Develop access-boundary requirements before implementing features that store or retrieve user-specific data; do not postpone authorization design until deployment.

## Definition of completion

A portfolio implementation of all nine stages is complete when each stage's completion evidence is demonstrated, the test/evaluation results are reproducible, deployment documentation works, and limitations are explicit.

Production acceptance additionally requires agreed security and quality thresholds, realistic load testing, tested recovery procedures, and review against the actual deployment's requirements. Small-corpus perfect scores do not replace these checks.
