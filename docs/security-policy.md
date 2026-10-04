# Stage 8 security and access policy

Stage 8 adds application-level controls; it does not certify this service for
production or replace an identity-provider, infrastructure, and data-protection
review. The API fails closed until `AUTH_ISSUER`, `AUTH_AUDIENCE`, and an HTTPS
`AUTH_JWKS_URL` are configured. It accepts RS256 signed JWT access tokens with
`typ: at+jwt`, matching issuer and audience, and required expiry, issue time,
subject, and tenant claims. The configured tenant, groups, and roles claims
must be issued by the trusted identity provider, not supplied in API bodies.

Every document, query, and session endpoint requires a bearer token. Root,
shallow health, and liveness remain unauthenticated; readiness requires a token.
The signed subject and tenant determine scope: `public`, `user:<subject>`, and
the actor's signed groups within that tenant. A token cannot claim a group in
the reserved `user:` namespace. Retrieval applies scope in SQL before text is
returned to rerankers, tools, prompts, or citations. Session access additionally
requires the creating subject, current tenant/scope, and the separate session
capability token. Pre-migration sessions become owned by `legacy` and are not
accessible to authenticated subjects.

`document:write` permits upload. An upload is private to `user:<subject>` by
default. To share it, multipart `access_groups` may list only the actor's
signed groups; `public` additionally requires `document:publish`. Replacement,
reindexing, and deletion require `document:manage` and visibility within the
tenant. Grant that high-trust management role sparingly: it permits managing
any visible document in the tenant, not just documents the actor uploaded.
Content deduplication is tenant-scoped and refuses reuse when access-group
sets differ. The current uniqueness constraint also prevents storing the same
content twice in one tenant with different group sets; change its content or
manage the existing document's policy through a future audited workflow.

Upload ingestion rejects recognizable credentials, US SSNs, Luhn-valid payment
card numbers, and high-confidence embedded instructions before embedding or
storage. Search and answer queries reject recognizable credentials and high-risk
PII. These are heuristic controls, **not comprehensive DLP**. Ordinary contact
details are allowed inside access-controlled documents; administrators must
classify data and configure retention under their own policy. No tokens,
prompts, source text, or document bodies are intentionally written to audit
logs. Audit records include action, decision, tenant, and a truncated hash of
the subject. PostgreSQL documents persist until explicit deletion; sessions
expire after the configured TTL and are purged on new-session creation or by
`python -m app.memory.conversation_memory --purge-expired`. There is no general
document-retention or legal-hold automation.

Limits include a 10 MiB default upload maximum, bounded query/history/tool and
model budgets, a 60-request/minute default sliding window per identity, and
eight concurrent requests per application process by default. The rate and
concurrency gates are in-memory/per-process, not shared across workers or
replicas. Deploy behind TLS and a network ingress with distributed admission,
request-body protection, secret management, and egress restrictions; those
infrastructure controls belong to Stage 9. Never expose the local stdio MCP
server as an unauthenticated network service: it uses a fixed public scope and
is intended only for trusted local use.

`tests/test_stage8_auth.py`, `tests/test_stage8_guardrails.py`, and
`tests/integration/test_postgres_access.py` cover signed-token validation,
permissions, sensitive inputs, scope, sessions, and real PostgreSQL isolation.
The local `app.evaluation.security_runner` inserts a synthetic malicious
legacy document directly into a unique tenant, tests authorized and denied
group retrieval, and removes it. In the recorded run the model followed the
embedded directive, but its uncited output was rejected by citation validation;
the `/ask` API would return 502 rather than release that text. This is a
defense-in-depth observation, **not proof that document injection is solved**.
Valid-looking cited malicious output and subtler attacks remain risks requiring
expanded adversarial evaluation and human review.
