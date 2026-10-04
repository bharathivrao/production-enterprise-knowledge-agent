# Stage 5 read-only tools and MCP boundary

`POST /ask/tools` is an opt-in tool-enabled counterpart to `/ask/planned`.
The existing `/ask` and `/ask/planned` remain unchanged. The tool workflow
accepts `query` and `top_k` only; callers cannot set tenant, principals, or
document scope.

## Tool contract

| Tool | Validated input | Result |
|---|---|---|
| `search_documents` | Query of 3–300 characters; `top_k` 1–3 | Scoped chunk IDs, document locations, and at most 200 characters of preview per hit |
| `read_document_chunks` | One to three UUID chunk IDs | Full text and source metadata for authorized, current chunks |

Both calls pass through `ToolDispatcher`. Unknown names, extra arguments,
invalid types, exhausted call budgets, missing/unauthorized chunks, and
dependency failures produce controlled errors. The read SQL joins chunks to
documents and applies the same parameterized tenant, access-group, validity,
version, and document filters as search. Missing and unauthorized IDs have the
same `not_found` response. No write operations are registered.

The Stage 4 planner still proposes bounded search queries. Stage 5 routes
those steps through `search_documents`, then a structured model choice selects
up to three returned chunk IDs for `read_document_chunks`. The server checks
that every selected ID came from scoped search and that explicitly named
documents are represented when available. Full text reaches synthesis only
after the scoped read. Model output cannot invoke other tools or supply scope.

Defaults for the tool-enabled path are five total steps (up to three searches,
one read, synthesis), seven model calls, four tool calls, 12,000 accounted
tokens, a 600-second workflow runtime, and a 120-second cooperative per-tool
limit. The shared Ollama client and PostgreSQL also have dependency timeouts.
In-flight calls cannot be forcibly cancelled exactly at the tool or workflow
deadline. Trace events record tool name, status, elapsed time, argument *sizes*,
and result counts—not raw questions, chunk IDs, or document text.

## MCP

`app/tools/mcp_server.py` exposes the same two dispatcher-backed tools through
a **local stdio MCP server**:

```bash
.venv/bin/python -m app.tools.mcp_server
```

Configure a trusted local MCP client to launch that command from the project
root. Do not expose it as a network service. The adapter uses only
`PUBLIC_SCOPE`; it does not implement user authentication or tenant delegation.
An HTTP MCP endpoint would require authentication and deployment policy in
Stage 8/9. The official [MCP Python server guide](https://modelcontextprotocol.io/docs/develop/build-server)
describes stdio server wiring and warns against stdout logging on that
transport. This server writes no application messages to stdout.

## Verification and limitations

The saved real local reports in `evals/results/stage5-*.json` include a
two-document tool comparison, a three-document tool comparison, and an
underspecified question that clarified without calling tools. The
two-document run searched, read two selected chunks, cited both named
documents, and completed in about 14.9 seconds with six model calls and 1,738
accounted tokens. The three-document run read three chunks and correctly
reported the retry limit and delay, but its final answer cited only two of the
three named documents; the incident-response finding cited the ownership guide
instead of the incident runbook. The current citation validator checks source
IDs, not semantic source suitability. Treat this as an answer-quality gap for
later evidence checking, not a successful three-source citation gate.

Unit/API tests cover contracts, allowlisting, budgets, redacted traces, model
choices, and controlled failures. A real stdio MCP client test checks tool
registration and argument rejection. The opt-in PostgreSQL test checks that
the read tool rejects private, other-tenant, and superseded chunks. These
tests do not make the unauthenticated public scope suitable for real enterprise
data. Stage 6 memory, Stage 7 evidence checking, and Stage 8 identity and
authorization remain separate work.
