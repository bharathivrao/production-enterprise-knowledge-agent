# Stage 7 evidence checking and correction

`POST /ask/planned`, `POST /ask/tools`, and session turns now verify structured
findings before release. The legacy single-pass `POST /ask` remains unchanged.
This is a best-effort grounding check, not a proof of truth or enterprise
authorization.

## Contract

1. The planner searches under the server's retrieval scope and one fixed
   `as_of` timestamp. Tool mode reads full chunk text through the same scoped
   dispatcher; search previews cannot become answer evidence directly.
2. Synthesis proposes one finding and citation IDs per deliverable. The
   existing structural renderer rejects invented IDs and malformed findings.
3. A structured model checker reviews each finding against the cited evidence
   for support, contradiction, and coverage. It has no reference answer. A
   server-owned rule additionally rejects findings that fail to cite an
   explicitly requested document when the corresponding search step uniquely
   names that document. The rule never forces an irrelevant citation: the
   finding may instead be marked as missing.
4. If any finding fails, the workflow can run **one** targeted, non-repeated
   search and one revision. Tool-mode correction reads any new chunk IDs
   through the same scoped dispatcher. The revision is structurally validated
   and checked again. There is no recursive agent loop.
5. Findings that still fail are replaced with `Not specified in the retrieved
   evidence.` and lose their citations. If none remain supported, the entire
   answer is the standard abstention. A checker outage or invalid first review
   releases no unreviewed draft; a correction failure retains only findings
   supported in the first review.

The response trace records checking, optional correction search/revision,
result counts, and sanitized failure class, without document text or the search
query. Metadata versions the critic prompt and states the one-correction cap.
The pre-existing step cap applies to the initial plan. Defaults allow ten
model calls for planned mode, eleven for tool mode, twelve including the
session resolver, and six tool calls in tool mode. The shared token/time caps
remain cooperative; an in-flight model call is not hard-cancelled.

## Evaluation and limitations

The Stage 5 saved three-source run answered the incident responder using only
the ownership-guide citation, omitting the explicitly requested incident
runbook. Stage 7's local replay is in
`evals/results/stage7-three-source-comparison.json`: one correction search
and revision produced a final answer citing all three requested documents,
with no failed check. The replay took about 25.4 seconds, eleven model calls,
and 3,985 accounted tokens versus the Stage 5 baseline's 13.7 seconds, seven
calls, and 2,147 tokens. This demonstrates a quality/latency tradeoff for
one case, not a general improvement rate. Deterministic tests also cover a
weak draft repaired by one scoped search and a revision,
repeated-query suppression, reviewer failure, and exhausted correction.
The Stage 7 two-turn session replay is saved as
`evals/results/stage7-session-followup.json`: all five follow-up checks passed,
and the temporary session was deleted without saving its bearer token.

The checker uses the same local generation model as synthesis and can make
false-positive or false-negative judgments. Explicit document-name matching
is heuristic and cannot resolve every alias. The current sample corpus and
handful of workflow scenarios are too small to claim production quality.
Before real use, expand development evaluations with independently reviewed
claim-support labels; preserve the held-out split for acceptance. Stage 8
still owns identity, authorization policy, prompt-injection testing, and
rate/resource controls.

## Reproduce

With the sample corpus in PostgreSQL and Ollama available:

```bash
.venv/bin/pytest -q
env RUN_POSTGRES_INTEGRATION=1 .venv/bin/pytest -q tests/integration
.venv/bin/python -m app.agents.workflow \
  "Compare the payment incident runbook, service ownership guide, and current payment retry policy: who responds to a severity-one payment incident, who owns the payments platform, and what retry count and delay apply to payment submissions?" \
  --tools --output evals/results/stage7-three-source-comparison.json
```

Review the trace and cited evidence manually; a passing test suite or an LLM
review alone does not establish factual correctness.
