# Codex Handoff — Production Enterprise Knowledge Agent

Updated: 2026-10-04 (America/Toronto)

## Objective

Build a production-oriented enterprise knowledge agent that ingests business
documents, retrieves permission-scoped evidence, answers with citations, and
eventually plans and executes bounded workflows with tools, memory, verification,
and security controls. The project is being delivered in nine roadmap stages.
Stages 1 and 2 are implemented and reviewed. Stage 3 (evaluation and quality
measurement) is complete pending owner review; Stage 4 and later stages have
not been started. The project is not yet a complete agent or production-ready
enterprise service.

## Current architecture

- FastAPI application (`app/main.py`) with Pydantic settings and API schemas.
- PostgreSQL 17 with pgvector, accessed through psycopg/pooling; Docker Compose
  exposes the local database on `127.0.0.1:5433`.
- Ingestion supports PDF, TXT, Markdown, and DOCX. Documents are chunked,
  embedded with Ollama `embeddinggemma`, and stored with provenance and source
  metadata.
- Retrieval includes vector search, PostgreSQL full-text search, hybrid fusion,
  and an optional cross-encoder reranker. Vector remains the default based on
  Stage 2 measurements. Retrieval scopes are enforced server-side.
- Answer generation uses Ollama `qwen3:4b`, builds a bounded evidence context,
  instructs the model to answer only from evidence, validates citation IDs, and
  accepts only a short interrogative clarification without a citation when the
  question is underspecified. Factual answers still require valid citations.
- Stage 3 evaluation is implemented under `app/evaluation/`: versioned golden
  dataset and manifest; retrieval and answer runners; independent structured
  LLM grading with `gemma4:e4b`; human-label grader calibration; acceptance
  gates; and repeated-run comparison. Reports are JSON under `evals/results/`.

## Important design decisions

- Keep Stage 2's vector default: vector and hybrid tied for best MRR@3 in the
  small Stage 2 benchmark; reranking added latency without improving that
  benchmark. See `docs/retrieval-policy.md`.
- Keep development and held-out test cases distinct: Stage 3 has 50 cases, 35
  development and 15 test, versioned by a manifest. Use development for tuning;
  treat test as acceptance-only.
- Hash the dataset/manifest, corpus snapshot, answer prompt, and record model and
  retrieval configuration in reports to make comparisons auditable.
- Separate retrieval metrics: Hit@k is not Recall@k; reports include Hit rate,
  MRR, source Recall@k, context precision, full coverage, latency percentiles,
  and per-case failures.
- Keep per-case exception capture and atomic checkpoints so a dependency error
  does not discard a long answer-evaluation batch.
- Use claim-level support grading plus separate answerability and source checks.
  The grader is an estimate, not a replacement for human review.
- Distinguish answer, abstain, and clarify outcomes in the golden dataset; the
  `clarify` case must not be scored as a generic unsupported-answer abstention.
- Locally hosted inference has no per-token API charge; reports state `$0` API
  cost, but do not claim compute is free. Hardware and energy costs are not
  measured.
- The user requested the Stage 3 push. Its implementation was committed as
  `91df72d` and pushed to `origin/main`. Review each stage before beginning
  the next one.

## Completed functionality in this working tree

### Previously completed (already on `main`)

- Stage 1: multi-format ingestion, lifecycle APIs, provenance, PostgreSQL pool
  and readiness/lifecycle handling, Stage 1 migration, tests, documentation.
- Stage 2: PostgreSQL full-text/hybrid retrieval, cross-encoder reranking,
  permission/scope filters, version handling, context budget and documented
  retrieval policy/results.

### Stage 3 implementation

- Expanded `evals/golden_dataset.json` to 50 cases; added development/test split
  and explicit coverage metadata for multi-document, conflicting/versioned,
  ambiguous, unsupported, and adversarial questions.
- Added typed dataset/manifest validation and corpus/dataset hashing.
- Versioned answer and grader prompts; added an independent configurable
  evaluation model and diagnostic token/latency collection without changing
  normal API answer shape.
- Added answer and retrieval evaluation, including per-case exceptions,
  checkpointing, latency distributions, token usage, source coverage, and
  structured grader scores.
- Added acceptance thresholds and executable CI-friendly gate commands, grader
  calibration against human labels, repeatability checks, tests, and policy docs.
- Saved development and held-out evaluation reports, grader calibration, and
  repeatability results in `evals/results/`.

## Files changed for Stage 3

- Configuration/generation: `.env.example`, `app/core/config.py`,
  `app/generation/generator.py`, `app/generation/pipeline.py`.
- Evaluation implementation: `app/evaluation/answer_runner.py`,
  `app/evaluation/dataset.py`, `app/evaluation/generation.py`,
  `app/evaluation/runner.py`, plus new `calibration.py`, `gates.py`, and
  `repeatability.py`.
- Evaluation data/policy/results: `evals/golden_dataset.json`,
  `evals/dataset_manifest.json`, `evals/acceptance_thresholds.json`,
  `evals/grader_calibration.json`, `evals/results/stage3-*.json`,
  `docs/evaluation-policy.md`.
- Tests: `tests/test_evaluation.py` and new
  `tests/test_evaluation_dataset.py`, `tests/test_evaluation_gates.py`,
  `tests/test_generation_evaluation.py`, `tests/test_repeatability.py`; also
  `tests/test_answer_evaluation.py` and `tests/test_generation_pipeline.py` for
  clarification behavior.
- Project status: `PROJECT_ROADMAP.md`, `README.md`, `docs/evaluation-policy.md`.
- This handoff: `CODEX_HANDOFF.md`.

## Current state and measured results

Branch is `main`, tracking `origin/main`. Stage 3 implementation commit
`91df72d feat: complete stage 3 evaluation and quality gates` was pushed to
GitHub. No Stage 4 work has been started.

- Unit suite: **65 passed, 2 skipped** (`.venv/bin/pytest -q`). Skips are
  environment-dependent tests; use the opt-in PostgreSQL integration command
  below when Docker/database is available.
- Retrieval held-out report: `evals/results/stage3-retrieval-test.json`;
  11 answerable cases evaluated, zero failures, Hit 1.0, MRR 0.9091, Recall@3
  1.0, context precision 0.4242. Retrieval gate passes.
- Answer development report: `evals/results/stage3-answers-development.json`;
  dataset and prompt v3.1.0, 35/35 completed, zero failures; correctness
  3.914/4, completeness 3.771/4, faithfulness 4/4, relevance 4/4, claim
  citation support 0.971, abstention/clarification behavior 1.0,
  citation-source accuracy 0.971. Answer development gate passes.
- Answer held-out report: `evals/results/stage3-answers-test.json`; dataset and
  prompt v3.1.0, 15/15 completed, zero failures; correctness, completeness,
  faithfulness, relevance, claim citation support, abstention/clarification
  behavior, and citation-source accuracy all 1.0. The answer acceptance gate
  passes. This small held-out corpus is not a general production-quality proof.
- Grader calibration: `evals/results/stage3-grader-calibration.json`;
  MAE 0.46875 and within-one rate 0.875. Calibration gate passes.
- Repeatability: `evals/results/stage3-repeatability.json`; final prompt v3.1.0,
  5 development cases × 3 runs, answer agreement 1.0 and citation agreement
  1.0.

The first v3.0 held-out run exposed over-citation and a clarification pipeline
error. Prompt v3.1.0 asks for minimal directly supportive citations and for
clarification when user intent is underspecified. The pipeline now accepts a
short, citation-free question-form clarification, while factual answers still
require citation validation. This change is covered by regression tests and
the final v3.1.0 held-out report passes the configured gates.

## Commands to run and test

Run from the repository root. Ensure `.env` is configured from `.env.example`,
Docker is available, and Ollama is running with `embeddinggemma`, `qwen3:4b`,
and `gemma4:e4b` pulled.

```bash
# Start PostgreSQL/pgvector
docker compose up -d db

# Start the API (in another terminal)
.venv/bin/uvicorn app.main:app --reload

# Unit/API suite
.venv/bin/pytest -q

# PostgreSQL integration suite (requires the local DB)
env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration

# Reproduce Stage 3 retrieval and answer evaluation
.venv/bin/python -m app.evaluation.runner --retriever vector --top-k 3 \
  --split development --output evals/results/stage3-retrieval-development.json
.venv/bin/python -m app.evaluation.runner --retriever vector --top-k 3 \
  --split test --output evals/results/stage3-retrieval-test.json
.venv/bin/python -m app.evaluation.answer_runner --split development --top-k 3 \
  --output evals/results/stage3-answers-development.json
.venv/bin/python -m app.evaluation.answer_runner --split test --top-k 3 \
  --output evals/results/stage3-answers-test.json

# Calibration and repeatability
.venv/bin/python -m app.evaluation.calibration \
  --output evals/results/stage3-grader-calibration.json
.venv/bin/python -m app.evaluation.repeatability --runs 3 --case-limit 5 \
  --output evals/results/stage3-repeatability.json

# Acceptance gates
.venv/bin/python -m app.evaluation.gates --kind retrieval \
  --report evals/results/stage3-retrieval-test.json
.venv/bin/python -m app.evaluation.gates --kind answer \
  --report evals/results/stage3-answers-test.json
.venv/bin/python -m app.evaluation.gates --kind grader_calibration \
  --report evals/results/stage3-grader-calibration.json
```

Evaluation runs require the populated local corpus in PostgreSQL and accessible
Ollama. In this session the sandbox could not reach localhost Ollama, so
repeatability required local runtime access; a fresh session may need the same
approved access. Test split is held out: tune only against development before
rerunning it for acceptance.

## Known issues and remaining work

- The initial evaluation dataset has 50 cases; eventual expansion to 100+
  remains desirable. Add cases to development first and preserve held-out split
  discipline.
- Human calibration covers eight labels and local automated grading can still
  mis-score. Sample judgments manually before release decisions.
- Clarification handling is intentionally narrow (short question-form output
  without citations); generalized goal analysis/planning belongs to Stage 4.
- Resource/energy costs are not measured; reported local API cost is $0 only.
- The full end-to-end production vision remains incomplete: planning, tools,
  memory, verification loops, enterprise identity/authorization, operational
  hardening/deployment and CI wiring are later roadmap stages.
- Stage 3 is marked complete pending owner review in `PROJECT_ROADMAP.md`.
  Stage 4 remains untouched.

## Exact recommended next task

Review Stage 3's implementation, reports, measured trade-offs, and the updated
`README.md`/`PROJECT_ROADMAP.md`, then approve or request adjustments. After
Stage 3 review is approved, the next roadmap task is Stage 4: define typed
goal/plan schemas (objective,
entities, deliverables, constraints, bounded steps), decompose complex queries,
and request clarification when intent is underspecified. Stage 4 has not been
started in this change set.
