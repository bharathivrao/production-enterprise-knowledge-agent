# Evaluation policy

## Dataset and split discipline

Dataset version `3.1.0` contains 50 cases: 35 development cases and 15 held-out
test cases. The manifest validates that IDs are unique, splits are disjoint and
exhaustive, and answerable cases declare sources. Coverage explicitly includes
multi-document, conflicting/versioned, ambiguous, unsupported, and adversarial
questions.

The answer contract distinguishes an evidence-supported answer, an explicit
abstention, and a clarification request. The ambiguous case is annotated with
`expected_behavior: "clarify"`; a concise question without citations is scored
as the correct behavior rather than forced into the unsupported-answer string.

Use the development split for prompt, retrieval, and threshold changes. Run the
held-out split only as an acceptance check after choices are fixed. Dataset and
corpus SHA-256 hashes are embedded in every report so results cannot be compared
silently across different inputs.

## Retrieval evaluation

Retrieval reports distinguish:

- Hit@k: whether at least one relevant source was found. This is not called recall.
- MRR@k: reciprocal rank of the first relevant source.
- Recall@k: fraction of all expected sources retrieved.
- Context precision: fraction of returned source locations that are relevant.
- Full coverage: whether every expected source was retrieved, important for
  multi-document questions.
- Per-case dependency errors and success rate.
- Min/mean/p50/p95/p99/max latency.

## Answer evaluation

Answers are scored from 0–4 for factual correctness, completeness, faithfulness,
and relevance. Citation support is calculated per factual claim rather than only
checking that a citation ID exists. Structural citation/source validation and
unsupported-question abstention are reported separately. The generation prompt
asks for minimal direct citations, discourages citations to unrelated retrieved
sources, and requests clarification for questions too vague to ground in a
specific user goal or situation.

`qwen3:4b` generates answers. The independent local `gemma4:e4b` evaluation model
grades them from the expected answer and retrieved evidence. The grader passed an
eight-case human-label calibration gate with mean absolute error 0.46875 and
87.5% of scores within one point. Automated grades remain estimates; material
release decisions still require sampling cases for human review.

Each answer report records retrieval, generation, grader, and total latency;
answer/grader prompt and completion tokens; context tokens; model identifiers;
prompt/grader versions; and local cost basis. Local inference has no per-token API
charge, so estimated API cost is recorded as $0 rather than pretending compute is
free. Infrastructure energy and hardware amortization are not currently measured.

The runner catches and records each case exception and atomically checkpoints the
report after every case. One failed request therefore cannot erase a long run.

## Repeatability and acceptance gates

Temperature is zero, but repeatability is measured rather than assumed. Repeated
runs compare normalized answers and exact citation sets and retain every output.

Thresholds live in `evals/acceptance_thresholds.json`. The gate command exits
non-zero for missing, null, or out-of-range metrics, making it suitable for CI:

```bash
python -m app.evaluation.gates \
  --kind retrieval \
  --report evals/results/stage3-retrieval-test.json
```

Equivalent gates exist for answer quality and grader calibration. CI wiring is
part of Stage 9, while Stage 3 owns the versioned thresholds and executable gate.

## Reproduction commands

```bash
python -m app.evaluation.runner --retriever vector --top-k 3 \
  --split development --output evals/results/stage3-retrieval-development.json

python -m app.evaluation.answer_runner --split development --top-k 3 \
  --output evals/results/stage3-answers-development.json

python -m app.evaluation.calibration \
  --output evals/results/stage3-grader-calibration.json

python -m app.evaluation.repeatability --runs 3 --case-limit 5 \
  --output evals/results/stage3-repeatability.json
```
