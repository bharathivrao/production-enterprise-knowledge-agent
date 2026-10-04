# Production Enterprise Knowledge Agent — Status and Remaining Roadmap

Updated: October 4, 2026

## Purpose and scope

This document records the implemented system and the work remaining to complete the original enterprise knowledge agent vision. The original plan described eight learning milestones; this roadmap uses the nine-stage structure agreed in the conversation, including service completion and packaging/deployment.

The target system accepts enterprise documents, answers questions with supporting evidence, decomposes complex tasks, uses tools, maintains memory, checks its work, and enforces access and safety policies.

Current status: Stages 1–4 are implemented pending owner review. The service has multi-format ingestion, scoped retrieval, versioned evaluation with passing held-out quality gates, and an opt-in bounded planning workflow. It is not yet a complete agent or a production-ready enterprise service.

Status is based on inspected repository code and recorded evaluation results. Empty placeholder files do not count as implemented features. Checklists below are completion targets, not claims that the features already exist.

## What is already built

### Application and configuration

- FastAPI application with document upload, search, single-pass answer, planned answer, root, health, liveness, and dependency-readiness endpoints.
- Pydantic request validation and structured ingestion/answer responses.
- Central settings loaded from environment configuration, with the database password represented as a SecretStr.
- PostgreSQL with pgvector provisioned through Docker Compose.
- Local Ollama models: embeddinggemma for embeddings and qwen3:4b for answer generation.
- Shared Ollama client with a five-second connection timeout and 120-second network timeout. This is not a total request deadline.

### Multi-format ingestion and persistence

- PDF, UTF-8 TXT, Markdown, and DOCX parsing with page or section metadata.
- Rejection of unsupported, unreadable, password-protected, empty, and textless content through the implemented validation paths.
- Token-based chunking with configurable size and overlap.
- Local 768-dimensional embeddings with truncation disabled.
- PostgreSQL document/chunk storage, foreign keys, uniqueness constraints, and dimensionality checks.
- SHA-256 content deduplication, including early reuse and storage-conflict handling.
- Upload response distinguishes newly created documents from reused documents.
- A 10 MiB upload check in the endpoint, plus temporary file cleanup.

### Retrieval and generation

- Vector search using pgvector cosine distance.
- Chunk IDs and source metadata in retrieval results.
- PostgreSQL full-text ranking, with shared query/document tokenization and common-word filtering.
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
- Stage 4 full local suite: 84 passed, 2 skipped. Real local PostgreSQL/Ollama planned runs also completed; the suite result does not imply production readiness.

### Evaluation

- Versioned 50-case golden dataset (35 development, 15 held-out test), with
  coverage for multi-document, conflicting/versioned, ambiguous, unsupported,
  and adversarial questions.
- Retrieval runner reports Hit@k, MRR, Recall@k, context precision, coverage,
  latency distributions, and dependency failures.
- Answer runner scores correctness, completeness, faithfulness, relevance,
  claim-level citation support, answer/abstain/clarify behavior, and citation
  source accuracy; it captures latency, tokens, and per-case failures.
- Prompt, grader, dataset/manifest, corpus, models, and retrieval configuration
  are versioned or hashed in reports. Grader calibration, repeatability reports,
  explicit acceptance thresholds, and executable gates are included.

### Goal analysis and planning

- Opt-in `/ask/planned` and CLI workflow with typed goals, deliverables, read-only
  search steps, server-owned synthesis, clarification, traces, and bounded usage.
- Model-proposed queries are validated before execution; retrieved evidence is
  permission-scoped and final citations are checked against source IDs.
- See `docs/planning-policy.md` and `evals/results/stage4-*.json` for the
  execution contract, measured examples, and limitations.

## Recorded results and their limits

| Evaluation | Recorded result |
|---|---|
| Stage 2 vector and hybrid comparison | MRR@3: 0.9643 for both on the measured set |
| Stage 3 held-out retrieval | Hit@3: 1.0; MRR@3: 0.9091; Recall@3: 1.0 |
| Stage 3 held-out answers | 15/15 completed; configured answer gate passes |
| Stage 4 planned three-source example | Three named sources cited; six model calls; about 9.3 seconds |

These results describe a small local corpus. Stage 3 held-out cases were kept
separate from development prompt tuning. They do not establish general
production quality.

Citation-ID validation proves that cited IDs exist. The answer evaluator scores
claim support and checks citation sources, but automated grading does not
prove that every claim follows from its passage or that an answer is complete.

Observed examples demonstrate why this matters: a privacy answer once omitted the instruction to redact; a retry answer lost the qualifier “up to”; an approval answer once inferred authority from investigation responsibility. Later experiments improved several of these behaviors, but factual review remains necessary.

## Nine-stage production roadmap

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

Status: completed October 4, 2026; pending owner review.

- [x] Expand to approximately 50 varied questions initially; eventual expansion to 100+ remains a dataset-growth goal.
- [x] Separate development questions from a held-out test set.
- [x] Cover multi-document, ambiguous, conflicting, unsupported, and adversarial questions.
- [x] Score factual correctness, completeness, faithfulness, answer relevance, and claim-level citation support.
- [x] Add Recall@k/context precision where applicable; do not label the current Hit@k metric as Recall@k.
- [x] Record latency distributions, token usage, dependency failures, and relevant resource/cost measurements; local hardware/energy costs remain unmeasured.
- [x] Version prompts, datasets, corpus snapshots, model identifiers, and retrieval configuration.
- [x] Add repeatability checks and record variation across runs.
- [x] Capture per-case exceptions so one failed request does not lose the whole evaluation run.
- [x] Define explicit acceptance thresholds and executable CI regression gates (CI wiring remains Stage 9).
- [x] Calibrate automated graders against human review when introducing model-based evaluation.

Completion evidence: 50-case, split-aware reports separate retrieval failures,
unsupported/ambiguous behavior, citation-source accuracy, claim support, and
answer quality. Retrieval, answer development, answer held-out, and grader
calibration gates pass. Five development questions repeated three times had
1.0 normalized answer and citation agreement. See `docs/evaluation-policy.md`
and `evals/results/stage3-*.json`.

Evidence: held-out retrieval achieved Hit@3 1.0, MRR@3 0.9091, and Recall@3
1.0. Held-out answers completed 15/15 cases with zero runner failures;
correctness, completeness, faithfulness, relevance, claim citation support,
abstention and citation-source accuracy each scored 1.0 in this small set. The
eight-label grader calibration achieved MAE 0.46875 and 0.875 within one point.
These local, small-corpus results are not a general production-quality
guarantee; automated grades still require human sampling.

### 4. Goal analysis and planning

Status: completed October 4, 2026; pending owner review.

- [x] Define typed goal and plan schemas with objectives, entities, deliverables, constraints, and steps.
- [x] Decompose complex questions into bounded subqueries.
- [x] Identify questions requiring clarification instead of guessing missing user intent.
- [x] Validate model-produced plans and permitted step types.
- [x] Execute a workflow with explicit states and observable transitions.
- [x] Bound step count, model calls, tokens, and total runtime (cooperative elapsed-time checks; hard cancellation remains future work).
- [x] Test comparisons spanning several runbooks or systems.

Completion evidence: a complex question yields a valid plan, executes it within limits, and produces a cited answer.

Evidence: 84 unit/API tests passed, 2 opt-in PostgreSQL integration tests
passed separately. Three real local PostgreSQL/Ollama runs are saved: a two-document
comparison, a three-document comparison with citations to all three named
sources, and an underspecified question that returns clarification before
search. The three-document run stayed within four steps, six model calls,
1,287 accounted tokens, and about 9.3 seconds. See `docs/planning-policy.md`.

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

Status: database Compose setup and README exist; application container,
deployment automation, and dedicated structured logging remain incomplete.

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
