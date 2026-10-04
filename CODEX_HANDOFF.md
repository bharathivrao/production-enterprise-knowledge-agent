# Codex Handoff — Production Enterprise Knowledge Agent

Updated: 2026-10-04 (America/Toronto)

## Objective and constraints

Build a production-oriented enterprise knowledge agent that ingests documents,
retrieves permission-scoped evidence, answers with citations, and eventually
supports bounded tools, memory, verification, access controls, and deployment.
The nine stages are in `PROJECT_ROADMAP.md`. The owner wants **one stage at a
time**, followed by an explanation of what it does and why and a request for
review. Do not begin the next stage before review. Stage 4 is implemented and
pending owner review. The owner requested a Stage 4 push after implementation;
verify the latest commit and remote state with `git status` and `git log` before
continuing. This is not yet safe for real enterprise data.

## Current architecture

- Python 3.14, FastAPI/Pydantic in `app/main.py` and `app/api/`. `POST /ask`
  remains single-pass RAG; `POST /ask/planned` is the opt-in Stage 4 workflow.
  Other endpoints cover documents, search, and health/readiness.
- PostgreSQL 17/pgvector via Docker Compose (`127.0.0.1:5433`) and psycopg
  pool. Ingestion parses PDF, TXT, Markdown, DOCX, chunks and embeds with
  Ollama `embeddinggemma`, and stores provenance and source metadata.
- Retrieval has permission-scoped vector search (measured default), PostgreSQL
  full-text search, hybrid fusion, and optional cross-encoder reranking.
  Single-pass answer generation uses Ollama `qwen3:4b`, bounded context,
  abstention/clarification, and citation-ID validation.
- Stage 3 evaluation in `app/evaluation/` uses a versioned 50-case dataset
  (35 development, 15 held-out), retrieval/answer runners, independent
  `gemma4:e4b` grading, calibration, repeatability, and executable gates.
- Stage 4 in `app/agents/` analyzes a typed goal, clarifies vague requests,
  validates a bounded read-only search plan, retrieves with a frozen as-of
  timestamp and server scope, and synthesizes structured cited findings.
  Response includes goal, plan, trace, usage, and metadata. Search calls the
  existing retriever directly, **not** a Stage 5 tool dispatcher.

## Important design decisions

- The model supplies objective, entities, constraints, and at most three
  deliverables, then one focused query per deliverable. The server constructs
  permitted `search` steps and the final `synthesize` step. Duplicate/invalid
  queries, wrong counts, and excessive plans fail closed; comparison goals
  require at least two distinct searches.
- Vague intent returns clarification before searching. A missing goal in
  model output also triggers a safe clarification rather than guessing.
- Searches use server-owned `PUBLIC_SCOPE` and one frozen `as_of` timestamp.
  Interleaved, deduplicated results help multi-document coverage. Explicit
  document titles can restrict answer context after scoped retrieval;
  unresolved aliases retain normally scoped candidates.
- Synthesis yields one finding per deliverable. Factual findings require known
  source IDs; an uncited finding must use the exact insufficient-evidence text.
  Server citation checks are structural, not semantic entailment verification.
- Defaults: four steps (three searches plus synthesis), six model calls,
  12,000 accounted tokens, 600 seconds, plus per-call output caps. Ollama chat
  tokens are reported; embedding query tokens are estimated. Runtime checks
  are cooperative: in-flight calls cannot be cancelled at the exact deadline.
- Stage 2 vector default is measurement-based. Stage 3 held-out cases are
  acceptance-only; tune on development data. Local-model API charge is $0,
  but hardware/energy costs are unmeasured.

## Completed functionality and files changed

Stages 1–3 are on `origin/main`. Stage 1 covers multi-format ingestion,
document lifecycle, provenance, database reliability and tests. Stage 2 covers
scoped search, full-text/hybrid retrieval, reranking and retrieval policy.
Stage 3 covers evaluation; implementation commit `91df72d` and README follow-up
`9232dd3` were pushed previously.

Stage 4 change set:

- `app/agents/goal_analyzer.py`: typed goal/clarification and structured Ollama
  analysis, version `4.0.0`.
- `app/agents/planner.py`: validated query draft and server-owned typed plan.
- `app/agents/synthesizer.py` (new): structured findings and checked citations.
- `app/agents/workflow.py`: states, execution, budgets, trace, metadata, CLI,
  and controlled failures.
- `app/api/query.py`: `POST /ask/planned` request/response and error mapping.
- `app/core/config.py`, `.env.example`: workflow limits.
- `tests/test_stage4_planning.py`, `tests/test_stage4_workflow.py`,
  `tests/test_stage4_synthesizer.py`, `tests/test_stage4_api.py` (new): plan
  validation, clarification, multi-source citations, scope, budgets, errors.
- `docs/planning-policy.md` (new), `PROJECT_ROADMAP.md`, `README.md`, this
  handoff: contract, status, commands, measured examples, limitations.
- `evals/results/stage4-planned-comparison.json`,
  `evals/results/stage4-three-source-comparison.json`, and
  `evals/results/stage4-clarification.json` (new): real local runs.

## Current state and tests

Branch `main` tracks `origin/main`. The full default suite passed:
**84 passed, 2 skipped** (`.venv/bin/pytest -q`). The two opt-in PostgreSQL
integration tests also passed separately with `RUN_POSTGRES_INTEGRATION=1`.
Real Stage 4 CLI runs used PostgreSQL and Ollama. `git diff --check` passed.

- Three-source comparison cited payment incident on-call response, Mercury
  ownership, and current retry policy v2 (up to two retries, at least 30
  seconds apart): about 9.3 seconds, six model calls, 1,287 accounted tokens.
- Two-source recovery comparison cited both named runbooks: about 11.4
  seconds, six calls, 1,289 tokens.
- “What should I do next?” returned clarification, no plan/search/citations,
  one model call, 149 tokens.
- Stage 3 held-out retrieval and answer gates pass on a small local dataset;
  see `docs/evaluation-policy.md` and `evals/results/stage3-*.json`. These are
  not general production-quality evidence.

## Commands to run and test

From the repository root, configure `.env` from `.env.example` (never commit
secrets), start Docker/Ollama, and pull `embeddinggemma`, `qwen3:4b`, and
`gemma4:e4b`:

```bash
uv sync --all-groups
docker compose up -d db
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest -q
env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration
git diff --check
```

Reproduce Stage 4 against the populated sample corpus:

```bash
.venv/bin/python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --output evals/results/stage4-three-source-comparison.json
.venv/bin/python -m app.agents.workflow "What should I do next?" \
  --output evals/results/stage4-clarification.json
```

Alternatively POST `{"query":"...","top_k":3}` to `/ask/planned`. See
`README.md` for setup and `docs/planning-policy.md` for the execution contract.
The opt-in integration suite and local model/database runs need services;
sandboxed sessions may need localhost approval. Do not casually overwrite
saved reports when changing prompts.

## Known issues and remaining work

- Runtime budget is cooperative, not hard cancellation. Embedding token
  accounting is estimated; local compute cost is unmeasured.
- Citation IDs and locations are checked, not semantic claim support. Title
  matching is heuristic and may miss aliases. Three saved demonstrations are
  not a broad agent-quality benchmark.
- No Stage 5 tool dispatcher/MCP; no Stage 6 persistent isolated memory; no
  Stage 7 evidence critic/retry; no Stage 8 authentication/enterprise access
  policies; no Stage 9 complete packaging/deployment/CI. `PUBLIC_SCOPE` is
  server-owned but is not user authentication. Do not use real enterprise data.
- Stage 3's 50-case dataset is small and automated grading still needs human
  sampling; preserve split discipline when expanding it.

## Exact recommended next task

Present Stage 4 for owner review. Explain typed goals,
bounded server-validated plans, clarification, scoped search, citation-checked
synthesis, why the model cannot choose arbitrary steps, measured runs, and
limitations. Stop there. Only after owner review and explicit direction should
a later session start Stage 5 (typed read-only tool interfaces/dispatcher and
MCP boundary).
