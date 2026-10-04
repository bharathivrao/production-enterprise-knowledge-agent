# Codex handoff — enterprise knowledge agent

Updated: 2026-10-04 (America/Toronto)

## Objective and owner constraints

Build the nine-stage production-oriented enterprise knowledge agent in
`PROJECT_ROADMAP.md`: ingest enterprise documents, retrieve authorized
evidence, answer with citations, plan/use read-only tools, maintain scoped
memory, verify answers, enforce identity/safety policies, and deploy
operationally. The owner wants **one stage at a time**, an explanation of what
it does and why, then a review request. Do not start Stage 9 or push/commit
Stage 8 until the owner asks. Stage 8 implementation is in the working tree;
the starting `main` was `9acc358` and tracked `origin/main`. Recheck status in
a fresh session. Do not use real enterprise data yet.

## Current architecture

- Python 3.14, FastAPI/Pydantic. `app/main.py` owns lifespan and HTTP admission.
  `app/api/` provides documents, search, single-pass `/ask`, opt-in planned
  and tool-assisted answers, health/readiness, and conversation sessions.
- PostgreSQL 17/pgvector via Docker Compose, with a psycopg pool. Ingestion
  parses PDF/TXT/Markdown/DOCX, chunks, embeds with Ollama `embeddinggemma`,
  and stores provenance. Retrieval is tenant/group scoped in SQL: vector
  (measured default), PostgreSQL full-text, hybrid, optional reranking.
- Ollama `qwen3:4b` generates cited answers. Stage 4 adds typed bounded plans;
  Stage 5 adds read-only scoped search/chunk-read tools and trusted local stdio
  MCP; Stage 6 adds expiring PostgreSQL sessions and bounded recent user-turn
  memory; Stage 7 adds fallible evidence checking and one correction search.
- Stage 3 evaluation has 50 development/held-out cases, answer/retrieval
  scoring, calibrated grading and local quality gates. Stage 8 has a separate
  adversarial replay in `app/evaluation/security_runner.py`.
- Stage 8 authenticates RS256 JWT access tokens (`at+jwt`) with configured
  issuer/audience/HTTPS JWKS. Verified subject, tenant, groups, and roles
  determine document and session access. No request body may set scope.

## Important design decisions

- Authentication fails closed without IdP settings. The API accepts only
  access tokens, not ID tokens; validates signature, issuer, audience, expiry,
  issue time, subject, tenant, group, and role shapes. The configured IdP must
  issue authoritative tenant/groups/roles. Root/shallow health/liveness stay
  public; readiness and all functional endpoints require bearer auth.
- Actor scope contains `public`, `user:<signed sub>`, and signed groups within
  the signed tenant. `user:` is reserved and forbidden in group claims.
  Retrieval and tool SQL filters before text reaches prompts or rerankers.
- `document:write` permits upload, private to the subject by default. Sharing
  requires an actor-owned group; publishing `public` additionally requires
  `document:publish`. Replace/reindex/delete require the high-trust
  `document:manage` role **and** document visibility. Managers may manage any
  visible document in their tenant, not only their own uploads.
- Deduplication is tenant- and ACL-aware; same-content, different-ACL uploads
  are rejected because the existing unique key does not allow both copies.
- Sessions require verified subject + tenant/scope + separate 256-bit bearer
  capability. Existing sessions migrated to owner `legacy` are inaccessible
  to authenticated subjects. Sessions expire by configured TTL, are purged on
  session creation or CLI, and retain bounded turns.
- Recognizable credentials, SSNs, Luhn-valid cards, and high-confidence
  document instructions are rejected before embedding; sensitive queries are
  rejected before search. Heuristics are not complete DLP. Audit logs contain
  action/decision, tenant, and hashed subject, not tokens or content.
- Sliding-window request rate and bounded concurrent requests are in-memory
  **per process**, not distributed. Existing upload/query/tool/model budgets
  remain. The local stdio MCP adapter still uses fixed public scope and must
  never be exposed as an unauthenticated network service.
- Prompt-injection defenses are layered: ingestion screening, evidence-as-data
  prompts, and citation gates. The local adversarial replay showed the model
  followed a directive in a synthetic legacy document, but the uncited output
  was rejected. Do not claim the model resists injection; valid-looking cited
  attacks remain a risk.

## Stage 8 files changed

- `app/guardrails/auth.py` (new), `app/guardrails/pii.py`,
  `app/guardrails/injection.py`, `app/guardrails/policies.py`: JWT/roles/scope,
  sensitive-content checks, audit, in-process rate gate.
- `app/api/query.py`, `app/api/ingest.py`, `app/api/sessions.py`,
  `app/api/health.py`, `app/main.py`: authenticated endpoints, role checks,
  derived scope, sensitive-input rejection, admission control.
- `app/db/repository.py`, `app/ingestion/pipeline.py`: tenant/ACL-scoped
  document lookup, dedup, management, and pre-embedding rejection.
- `app/memory/conversation_memory.py`, `app/memory/session_workflow.py`,
  `scripts/schema.sql`, new `scripts/migrate_stage8.sql`: subject-bound sessions;
  additive migration was applied to the local development database.
- `app/core/config.py`, `.env.example`, `pyproject.toml`, `uv.lock`: auth/limit
  configuration and `PyJWT[crypto]>=2.15.1,<3`.
- `tests/conftest.py`, new `tests/test_stage8_auth.py`,
  `tests/test_stage8_guardrails.py`, `tests/integration/test_postgres_access.py`,
  plus regression updates in old API/pipeline tests.
- New `app/evaluation/security_runner.py`,
  `evals/results/stage8-security.json`, `docs/security-policy.md`; updated
  `README.md`, `PROJECT_ROADMAP.md`, this handoff.

## Current state, tests, and commands

Stage 8 is implemented but **uncommitted/unpushed and awaiting owner review**.
The local Stage 8 migration has run successfully. Run from repository root:

```bash
uv sync --all-groups
docker compose up -d db
ollama pull embeddinggemma
ollama pull qwen3:4b
ollama pull gemma4:e4b
# On an existing DB, apply earlier migrations first; Stage 8 migration:
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U knowledge_agent \
  -d knowledge_agent -f /dev/stdin < scripts/migrate_stage8.sql
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest -q
env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration
.venv/bin/python -m app.evaluation.security_runner \
  --output evals/results/stage8-security.json
git diff --check
```

Set `POSTGRES_PASSWORD` and `AUTH_ISSUER`, `AUTH_AUDIENCE`, HTTPS
`AUTH_JWKS_URL` in `.env`; the issuer must mint RS256 `at+jwt` access tokens
with `tenant_id`, `groups`, and `roles` claims, or map those names via the
`AUTH_*_CLAIM` settings. Never commit `.env` or bearer/session tokens. The
Stage 8 local default suite passed **144 tests, 4 skipped**. The opt-in
PostgreSQL suite passed **8 tests**. The adversarial report passed delivery and
isolation checks, while recording `model_followed_embedded_directive: true`
and `citation_gate_blocked_output: true`. Its fixture is deleted in `finally`.
Inspect its latest JSON before making model or prompt changes.

## Known issues and remaining work

- No real IdP has been configured or tested against this deployment; auth is
  fail-closed until configured. TLS, network ingress, centralized secrets,
  distributed throttling, logging/metrics, CI, container packaging, backups,
  load/recovery tests, and operational runbooks are Stage 9.
- Prompt-injection screening and PII patterns are heuristic, not complete
  protection or redaction. The model followed a synthetic malicious legacy
  document instruction; citation validation prevented that specific uncited
  response. Further adversarial/human review is required.
- `document:manage` is tenant-wide over documents the manager can see.
  Fine-grained per-document owner-management and ACL editing do not exist.
  Same-content uploads with different ACL sets are rejected.
- Per-process rate/concurrency controls are not global and do not protect a
  multi-worker deployment alone. Runtime/model/tool deadlines are cooperative,
  not hard cancellation. No automatic general document retention/legal hold.
- Local stdio MCP is trusted/public-scope only. Stage 3's 50 cases and local
  adversarial replay are too small to establish production quality/security.

## Exact recommended next task

Review the Stage 8 implementation and tradeoffs with the owner. Do **not**
start Stage 9 or push until requested.
