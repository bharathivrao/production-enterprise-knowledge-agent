# Retrieval and reranking policy

## Default and measured alternatives

Vector search remains the default. Stage 2 evaluated every variant at `k=3` on
the same corpus and 14 answerable questions, including two multi-document cases
and one superseded-policy case.

| Retriever | Hit@3 | MRR@3 | Full source coverage | p50 latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| Vector | 100% | 0.9643 | 100% | 105.41 ms | 177.60 ms |
| Legacy in-memory BM25 baseline | 100% | 0.8690 | 100% | 1.41 ms | 3.15 ms |
| PostgreSQL FTS | 100% | 0.9286 | 100% | 1.61 ms | 4.35 ms |
| Hybrid RRF | 100% | 0.9643 | 100% | 98.46 ms | 105.43 ms |
| Hybrid + cross-encoder | 100% | 0.9286 | 100% | 138.30 ms | 199.46 ms |

These are small local-corpus measurements, not general production guarantees.
Hybrid added no quality over vector, and the cross-encoder reduced MRR while
adding latency. Both remain selectable through the API for future datasets, but
making either the default would not be justified by current evidence.

The cross-encoder is `cross-encoder/ms-marco-MiniLM-L6-v2`. It jointly scores
query/passage pairs and is applied only to 10 fused candidates by default. Testing
10, 20, and 40 candidates produced the same 100% source coverage and 0.9286 MRR;
10 was selected as the smallest equivalent candidate set. The implementation
uses the documented Sentence Transformers retrieve-and-rerank pattern:
<https://www.sbert.net/examples/cross_encoder/applications/README.html>.

## Index and budgets

Production keyword retrieval uses PostgreSQL `tsvector`, a GIN index, and
`ts_rank_cd`; it does not rebuild a corpus-wide Python BM25 index per request. The
old BM25 implementation remains evaluation-only so comparisons stay reproducible.
Vector search uses an HNSW cosine index. The default candidate count is 20, API
result count is at most 20, and evidence context is capped at 3,500 tokens.

The installed `embeddinggemma` reports a 2,048-token input limit and 768 output
dimensions. Chunks were reduced from 500 to 400 tokens with 50-token overlap:
this remains comfortably inside the embedding limit and leaves room within the
cross-encoder's 512-token query/passage limit. Existing corpus documents were
reindexed under this configuration.

## Access and evidence behavior

Every retriever applies the same server-derived scope in SQL before results enter
fusion, reranking, or prompts. The scope contains tenant, access-group principals,
optional document/content-type filters, and an as-of time. Query text and request
payloads cannot assign principals.

- Superseded documents are excluded when a higher active version exists in the
  same conflict group.
- Exact normalized duplicate passages are scored once; alternate provenance is
  retained, and duplicates are removed again before prompt construction.
- Current sources that genuinely disagree are kept. The generator must identify
  the conflict and cite both rather than silently choosing a side.
- Empty result sets cause abstention. Absolute vector/reranker score cutoffs are
  disabled until Stage 3 calibrates them; an uncalibrated cutoff caused relevant
  evidence loss during Stage 2 experiments. Configured cutoffs remain available.
- Expired documents and documents outside the caller's tenant or access groups
  never reach application-level ranking.

Raw reports are stored as `evals/results/stage2-*-top3.json` and include dataset
hashes, model/configuration identifiers, per-case rankings, source coverage, and
latency distributions.
