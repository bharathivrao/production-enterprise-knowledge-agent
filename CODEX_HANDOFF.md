# Codex Handoff — Production Enterprise Knowledge Agent

Updated: 2026-10-04 (America/Toronto)

## Objective and constraints

Build a production-oriented enterprise knowledge agent that ingests documents,
retrieves permission-scoped evidence, answers with citations, and eventually
supports bounded tools, memory, verification, access controls, and deployment.
The nine stages are in `PROJECT_ROADMAP.md`. The owner wants **one stage at a
time**, followed by an explanation of what it does and why and a request for
review. Do not begin the next stage before review. Stages 1–6 were pushed to
`origin/main` (Stage 6: `7089f31`). The owner approved Stage 7 for push to
`origin/main`; confirm the commit and remote branch with `git status -sb` and
`git log -1 --oneline` in a fresh session. The owner has not requested Stage 8
work. This is not safe for real enterprise data.

## Current architecture

- Python 3.14, FastAPI/Pydantic in `app/main.py` and `app/api/`. `POST /ask`
  remains single-pass RAG; `POST /ask/planned` is the Stage 4 workflow;
  `POST /ask/tools` is the opt-in Stage 5 tool-enabled workflow. Other
  endpoints cover documents, search, and health/readiness. Stage 6 adds
  `POST /sessions`, `POST /sessions/{id}/ask`, and token-protected history,
  reset, and delete endpoints.
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
  existing retriever directly, preserving Stage 4 behavior.
- Stage 5 (`app/tools/`, `app/agents/tool_selector.py`) routes the tool-enabled
  path through validated, read-only search and scoped chunk-read tools. Search
  returns previews and IDs; a structured model choice selects up to three
  numbered candidates, which the server maps to IDs for a scoped full-text
  read. A local stdio MCP server
  exposes the same dispatcher with a fixed public scope; there is no HTTP MCP
  listener or user authentication.
- Stage 6 (`app/memory/`) stores capability-protected, expiring sessions and
  bounded turns in PostgreSQL. The request-scoped working memory tracks plan
  progress, tool observations, citations, and unresolved questions. A
  structured resolver uses recent user questions and reauthorized source
  titles, never old generated answers, then invokes Stage 5 retrieval anew.
- Stage 7 (`app/agents/critic.py`, `app/agents/workflow.py`) checks drafted
  findings against freshly retrieved evidence, enforces resolvable named
  document citation requirements, and permits one scoped correction/recheck.
  The legacy single-pass `/ask` path remains unchanged.

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
  Stage 7 adds fallible semantic checking and deterministic named-document
  coverage; no model review can prove claim support.
- Defaults: four initial-plan steps (three searches plus synthesis), ten model calls,
  12,000 accounted tokens, 600 seconds, plus per-call output caps. Ollama chat
  tokens are reported; embedding query tokens are estimated. Runtime checks
  are cooperative: in-flight calls cannot be cancelled at the exact deadline.
- Stage 5 tool mode separately permits five initial-plan steps, eleven model calls, six
  tool calls, and one read of up to three chunks. `ToolDispatcher` rejects
  unknown names, extra/invalid arguments, exhausted budgets and missing or
  unauthorized chunk IDs. Its read SQL reuses `document_filter_sql`, so tenant,
  access groups, validity, latest version, and document filters apply before
  content leaves PostgreSQL. Missing and denied IDs are indistinguishable.
  Traces record argument sizes, result counts, status, and timing—not raw text.
- MCP uses stdio only to avoid exposing an unauthenticated network tool
  endpoint. This is an intentional Stage 5 boundary, not Stage 8 identity.
- Stage 6 session credentials are 256-bit opaque bearer tokens returned once;
  only SHA-256 hashes are stored. Sessions use the server's public scope and
  fixed 24-hour expiry. Wrong token, scope, missing ID, and expired ID all
  appear as not found. No real user identity or delegated tenant access exists.
- Store at most 12 turns; select up to six recent whole turns and 1,200 tokens
  for reference resolution. Resolver input excludes previous model answers
  and filters remembered citation titles through the current retrieval scope.
  Each follow-up runs fresh scoped tools before answering. Optimistic version
  checks return 409 on concurrent stale writes or reset races; no DB lock is
  held during model calls. Expired rows purge on session creation or via CLI.
- Combined session limits are twelve model calls, 14,000 accounted tokens, and
  750 seconds, cooperatively checked. Stage 6's session token is not a Stage 8
  authentication system, and no rate limiting is implemented.
- Stage 2 vector default is measurement-based. Stage 3 held-out cases are
  acceptance-only; tune on development data. Local-model API charge is $0,
  but hardware/energy costs are unmeasured.
- Stage 7 permits at most one novel correction search and one revision.
  Structural validation and semantic rechecking apply after revision;
  exhausted attempts mask unsupported findings or abstain. Checker failure
  cannot release an unchecked draft. Model/tool budgets include the retry.

## Completed functionality and files changed

Stages 1–5 are on `origin/main`. Stage 1 covers multi-format ingestion,
document lifecycle, provenance, database reliability and tests. Stage 2 covers
scoped search, full-text/hybrid retrieval, reranking and retrieval policy.
Stage 3 covers evaluation; implementation commit `91df72d` and README follow-up
`9232dd3` were pushed previously.
Stage 4 implementation was pushed as `3357599`.
Stage 5 read-only tools/MCP were pushed as `cb0ac3a`.
Stage 6 memory was pushed as `7089f31`.

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

Stage 5 change set:

- `app/tools/dispatcher.py`, `app/tools/__init__.py`: typed search/read
  contracts, scope-bound dispatch, allowlist, budgets and controlled errors.
- `app/tools/mcp_server.py`: local stdio MCP adapter with read-only tool hints.
- `app/agents/tool_selector.py`: structured model selection and validation of
  returned chunk IDs and named-document coverage.
- `app/agents/workflow.py`, `app/api/query.py`, `app/core/config.py`,
  `.env.example`: opt-in tool workflow/API, trace and limit settings.
- `pyproject.toml`, `uv.lock`: official Python `mcp` SDK v2 dependency.
- `tests/test_stage5_*.py`, `tests/integration/test_postgres_retrieval.py`:
  contracts, workflow/API/MCP boundaries, and real PostgreSQL read isolation.
- `docs/tool-policy.md`, `README.md`, `PROJECT_ROADMAP.md`, this handoff; three
  saved `evals/results/stage5-*.json` local workflow reports.

Stage 6 change set:

- `scripts/schema.sql`, new `scripts/migrate_stage6.sql`: session and turn
  tables, expiry/recent-turn indexes, cascading deletion. Migration applied
  successfully to the local development PostgreSQL database.
- `app/memory/conversation_memory.py`: create/load/append/reset/delete/purge,
  token hashing, version conflicts, turn pruning, source-title reauthorization.
- `app/memory/working_memory.py`: typed ephemeral state, bounded history
  selection, structured follow-up resolver, prompt v6.2.0.
- New `app/memory/session_workflow.py`: combined budgets and fresh scoped
  Stage 5 workflow per turn.
- New `app/api/sessions.py`, `app/main.py`: capability-protected session API.
- `app/core/config.py`, `.env.example`: Stage 6 limits and retention settings.
- `app/agents/tool_selector.py`, `app/agents/workflow.py`: numbered candidate
  selection replaces fragile model-copied UUIDs; explicit single document
  title phrases now restrict answer evidence appropriately. These are small
  Stage 5/4 reliability fixes discovered during Stage 6 live evaluation.
- New `app/evaluation/session_runner.py` and
  `evals/results/stage6-followup.json`: two-turn local behavior check; the
  report omits the session token and deletes its temporary session.
- New `tests/test_stage6_memory.py`, `tests/test_stage6_session_workflow.py`,
  `tests/test_stage6_api.py`, `tests/integration/test_postgres_memory.py`, plus
  focused regression updates in `tests/test_stage4_workflow.py` and
  `tests/test_stage5_selection.py`/`test_stage5_workflow.py`.
- New `docs/memory-policy.md`; updated `README.md`, `PROJECT_ROADMAP.md`,
  `docs/tool-policy.md`, and this handoff.

Stage 7 change set:

- New `app/agents/critic.py`: typed, reference-free finding reviews,
  per-deliverable verdicts, safe masking, and novel-query validation.
- `app/agents/workflow.py`: structural then semantic checks, explicit-document
  source alignment, one bounded scoped correction search/revision/recheck,
  fail-closed partial answers/abstention, redacted trace and version metadata.
- `app/agents/synthesizer.py`: versioned revision feedback sent as structured
  data. `app/core/config.py` and `.env.example`: expanded model/tool-call
  ceilings for one correction while preserving token/time limits.
- New `tests/test_stage7_critic.py` and `tests/test_stage7_workflow.py`, plus
  Stage 4/5 regression expectation updates. No schema change.
- New `docs/verification-policy.md` and
  `evals/results/stage7-three-source-comparison.json` and
  `evals/results/stage7-session-followup.json`; updated README,
  roadmap, and this handoff.

## Current state and tests

Branch `main` tracks `origin/main`; the owner requested a Stage 7 push. The full
default suite passed: **123 passed, 3 skipped** (`.venv/bin/pytest -q`). All
six opt-in PostgreSQL integration tests passed separately with
`RUN_POSTGRES_INTEGRATION=1`. New database tests cover session isolation,
concurrent turns, reset/deletion, pruning/expiry, and current-scope
reauthorization of remembered source titles. Stage 7's eight new tests cover
critic contracts, novel query suppression, correction, source alignment, and
fail-closed behavior. `git diff --check` passes.

The live Stage 7 three-source replay searched once more, revised, and cited
all three requested documents with no failed check. It used 11 model calls,
3,985 accounted tokens, and about 25.4 seconds, versus Stage 5's 7 calls,
2,147 tokens, and 13.7 seconds with only two source citations. This is one
local comparison, not a measured population-level gain. An intermediate run
with an invalid second critic output safely returned a partial answer; the
saved final report is the successful replay.
The Stage 7 two-turn session replay passed all five checks, including fresh
follow-up search and session cleanup; its report contains no bearer token.

The real `stage6-followup.json` scenario passed all five checks: turn one
cited the payment incident runbook; “Who owns that service?” resolved to the
payments platform, used fresh search/read tools, cited the service ownership
guide, and both turns persisted before the evaluation session was deleted.
Turn-one usage was five model calls/1,105 tokens; turn two was six calls/1,384
tokens. This is one local behavior example, not a general quality guarantee.

Stage 5 measured runs:

- `stage5-tool-comparison.json`: searched and read two named documents,
  cited both; about 14.9 seconds, six model calls, 1,738 accounted tokens.
- `stage5-three-source-comparison.json`: searched and read three documents,
  answered retry limit/delay correctly, but cited only two named documents;
  the incident finding cited the ownership guide rather than the runbook.
  This is an answer-quality gap, not a three-source citation pass.
- `stage5-clarification.json`: ambiguous question clarified without tools.

Earlier Stage 4 evidence remains in the saved reports:

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
# Required once for an existing PostgreSQL volume (already applied locally):
docker compose exec -T db psql -v ON_ERROR_STOP=1 \
  -U knowledge_agent -d knowledge_agent -f /dev/stdin < scripts/migrate_stage6.sql
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest -q
env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration
git diff --check
```

Reproduce Stage 6 against the populated sample corpus:

```bash
.venv/bin/python -m app.evaluation.session_runner \
  --output evals/results/stage6-followup.json
.venv/bin/python -m app.memory.conversation_memory --purge-expired
```

Reproduce Stage 7 (this overwrites the saved report, so use a different
output path if preserving the accepted local example):

```bash
.venv/bin/python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --tools --output /private/tmp/stage7-replay.json
```

Alternatively `POST /sessions`, save the returned one-time token privately,
then send it as `X-Session-Token` to `POST /sessions/{id}/ask` with
`{"query":"Who owns that service?","top_k":3}`. History, reset, and delete
use the same token. See `README.md` and `docs/memory-policy.md` for the full
contract. The evaluation report contains no token and its session is deleted.
The opt-in integration suite and local model/database runs need services;
sandboxed sessions may need localhost approval. Do not casually overwrite
saved reports when changing prompts.

## Known issues and remaining work

- Runtime budget is cooperative, not hard cancellation. Embedding token
  accounting is estimated; local compute cost is unmeasured.
- Stage 7's semantic reviewer is a fallible local model, not a guarantee of
  entailment. An intermediate local run returned a qualified partial answer
  after an invalid second review. Named-document matching is heuristic and
  can miss aliases. One successful correction is not a broad benchmark.
- MCP is local stdio/public-scope only; no remote authentication. Tool time
  limit checks are cooperative and do not forcibly cancel an in-flight call.
- Session bearer tokens protect a single session but do not establish a user
  identity. Anyone holding a token can read/delete that session; there is no
  rate limiting. Expired rows are purged on create or manually; scheduled
  cleanup belongs to Stage 9. Do not use real enterprise data.
- No Stage 8 authentication/enterprise access policies or Stage 9 complete
  packaging/deployment/CI. `PUBLIC_SCOPE` is
  server-owned but is not user authentication. Do not use real enterprise data.
- Stage 3's 50-case dataset is small and automated grading still needs human
  sampling; preserve split discipline when expanding it.

## Exact recommended next task

Stage 7 has been approved for push. Verify the branch is synchronized, then
wait for explicit owner direction before Stage 8. The next roadmap task is
Stage 8: authentication, per-user/tenant authorization, prompt-injection and
sensitive-data safeguards, and rate limits.
