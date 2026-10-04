# Stage 4 planning workflow

`POST /ask/planned` runs an opt-in, read-only workflow for questions that need
several pieces of evidence. The existing `POST /ask` remains the single-pass
answer path. The endpoint accepts `query` (1–2000 characters) and `top_k`
(1–3, default 3). It does not accept a caller-supplied tenant or permission
scope; retrieval uses the server's scope boundary.

## Execution contract

1. The goal analyzer returns a typed objective, entities, up to three
   deliverables, constraints, or one clarification question. A missing goal is
   treated as a need for clarification rather than an invitation to guess.
2. The planner produces exactly one focused search query per deliverable. The
   server validates the query count, uniqueness, length, comparison coverage,
   and step limit, then appends the sole permitted final `synthesize` step.
   Model output cannot add a write step or select arbitrary tools.
3. Each search uses the existing permission-filtered vector retriever with one
   frozen `as_of` timestamp. Results are interleaved across steps and duplicate
   content is removed. When the user's question names documents and those
   titles resolve against retrieved filenames, unrelated documents are left
   out of the answer context.
4. Synthesis returns one short structured finding per deliverable. Each finding
   names directly supporting source IDs, or explicitly says the retrieved
   evidence does not specify the answer. The server renders and validates the
   final citations. No retrieved document can change the permitted workflow
   steps.

The response includes `state`, `answer`, `citations`, `goal`, `plan`, `trace`,
`usage`, and version/model/limit metadata. The trace records state transitions
and result counts, without logging document text. Failures return a controlled
HTTP error with the completed transitions. Expected states include `received`,
`analyzing`, `planning`, `searching`, `searched`, `evidence_selected`,
`synthesizing`, `completed`, `clarification`, and `failed`.

## Limits

Defaults in `.env.example` are four total steps (up to three searches plus
synthesis), six model calls (goal, plan, three embeddings, synthesis), 12,000
accounted tokens, and 600 seconds. Analyzer/planner/synthesis output tokens
also have per-call caps. The workflow checks token and elapsed-time budgets
after each call and before starting another. The shared Ollama client has a
120-second network timeout and PostgreSQL has statement timeouts; an in-flight
call can still finish after the workflow's 600-second check, so this is not yet
a hard cancellation deadline. Chat token usage comes from Ollama; embedding
query tokens are estimated with `cl100k_base`.

## Reproduce the local evidence

With the sample corpus ingested in PostgreSQL and Ollama running, use:

```bash
python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --output evals/results/stage4-three-source-comparison.json

python -m app.agents.workflow "What should I do next?" \
  --output evals/results/stage4-clarification.json
```

The saved three-document run completed in about 9.3 seconds with six model
calls and 1,287 accounted tokens. It cited the payment incident runbook for
the on-call response, the service ownership guide for the Mercury team, and
the current version 2 retry policy for two retries with at least 30 seconds
between attempts. The vague question returned a clarification after one model
call, without searching. The two-document recovery comparison is saved at
`evals/results/stage4-planned-comparison.json`. These are local examples, not
a general quality benchmark.

## Current boundaries

- Search is the only executable step. Typed tool dispatch, document-reading
  tools, and MCP are Stage 5 work.
- The workflow does not store a conversation or plan progress across requests;
  memory is Stage 6 work.
- Citation validation confirms source IDs and locations, not that every claim
  is semantically entailed. Bounded evidence checking and correction are Stage
  7 work.
- The API currently uses the public server scope. User authentication and
  broader enterprise access policy are Stage 8 work.
- Filename matching is a conservative title heuristic and can miss aliases.
  When titles cannot be resolved, the workflow retains the retrieved candidates
  within the normal permission boundary.
