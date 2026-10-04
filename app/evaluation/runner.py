import json
from pathlib import Path
import argparse
from app.retrieval.vector_search import search_chunks
import hashlib
from datetime import datetime, timezone
from app.retrieval.bm25 import search_bm25_baseline, search_keyword
from app.core.config import get_settings
from app.retrieval.hybrid import search_hybrid
from app.retrieval.reranker import search_reranked
from time import perf_counter
from statistics import mean
from app.evaluation.dataset import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _latency_summary(values):
    if not values:
        return {"min": None, "mean": None, "p50": None, "p95": None, "p99": None, "max": None}
    ordered = sorted(values)

    def percentile(fraction):
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

    return {
        "min": ordered[0], "mean": mean(values), "p50": percentile(0.50),
        "p95": percentile(0.95), "p99": percentile(0.99), "max": ordered[-1],
    }


def run_retrieval_evaluation(
    top_k=3, retriever="vector", candidate_count=None, split="development",
):
    if retriever == "vector":
        search = search_chunks
        score_field = "distance"
    elif retriever == "bm25":
        search = search_bm25_baseline
        score_field = "bm25_score"
    elif retriever == "keyword":
        search = search_keyword
        score_field = "keyword_score"
    elif retriever == "hybrid":
        search = lambda query, top_k: search_hybrid(
            query, top_k=top_k, candidate_k=candidate_count,
        )
        score_field = "rrf_score"
    elif retriever == "reranked":
        search = lambda query, top_k: search_reranked(
            query, top_k=top_k, candidate_k=candidate_count,
        )
        score_field = "rerank_score"
    else:
        raise ValueError(f"Unknown retriever: {retriever}")
    
    bundle = load_dataset(PROJECT_ROOT, split=split)
    dataset = bundle.cases
    settings = get_settings()

    hits = 0
    evaluated = 0
    cases = []
    reciprocal_rank_total = 0.0
    full_coverage_count = 0
    source_recall_total = 0.0
    latencies_ms = []
    context_precision_total = 0.0
    failures = []

    for case in dataset:
        if not case.answerable:
            continue

        started = perf_counter()
        try:
            results = search(case.question, top_k=top_k)
        except Exception as error:
            latency_ms = (perf_counter() - started) * 1000
            latencies_ms.append(latency_ms)
            evaluated += 1
            failures.append({
                "id": case.id, "error_type": type(error).__name__, "error": str(error),
            })
            cases.append({"id": case.id, "error": failures[-1], "latency_ms": latency_ms})
            print(f"{case.id}: ERROR")
            continue
        latency_ms = (perf_counter() - started) * 1000
        latencies_ms.append(latency_ms)

        expected = case.expected_sources

        retrieved = {
            (result["document"], result["page"])
            for result in results
        }

        hit = bool(expected & retrieved)
        relevant_retrieved = expected & retrieved
        all_relevant_retrieved = expected <= retrieved
        source_recall = len(relevant_retrieved) / len(expected) if expected else 1.0
        context_precision = len(relevant_retrieved) / len(retrieved) if retrieved else 0.0

        first_relevant_rank = next(
            (
                rank
                for rank, result in enumerate(results, start=1)
                if (result["document"], result["page"]) in expected
            ),
            None,
        )

        reciprocal_rank = (
            1 / first_relevant_rank
            if first_relevant_rank is not None
            else 0.0
        )

        reciprocal_rank_total += reciprocal_rank

        hits += int(hit)
        full_coverage_count += int(all_relevant_retrieved)
        source_recall_total += source_recall
        context_precision_total += context_precision
        evaluated += 1

        cases.append({
            "id": case.id,
            "hit": hit,
            "all_relevant_retrieved": all_relevant_retrieved,
            "source_recall": source_recall,
            "context_precision": context_precision,
            "first_relevant_rank": first_relevant_rank,
            "reciprocal_rank": reciprocal_rank,     
            "latency_ms": latency_ms,
            "retrieved_sources": [
                {
                    "document": result["document"],
                    "page": result["page"],
                    score_field: result.get(score_field, result.get("bm25_score")),
                }
                for result in results
            ],
        })

        print(f"{case.id}: {'HIT' if hit else 'MISS'}")
       

    report = {
        "report_version": "3.0.0", "top_k": top_k, "split": split,
        "evaluated": evaluated,
        "hits": hits,
        "hit_rate": hits / evaluated if evaluated else None,
        "skipped_unanswerable": sum(
            not case.answerable for case in dataset
        ),
        "cases": cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retriever": retriever,
        "embedding_model": (
            settings.embedding_model
            if retriever in {"vector", "hybrid", "reranked"}
            else None
        ),
        "dataset_version": bundle.manifest.dataset_version,
        "dataset_sha256": bundle.dataset_sha256,
        "corpus_version": bundle.manifest.corpus_version,
        "corpus_sha256": bundle.corpus_sha256,
        "mrr": reciprocal_rank_total / evaluated if evaluated else None,
        "full_coverage_rate": full_coverage_count / evaluated if evaluated else None,
        "mean_source_recall": source_recall_total / evaluated if evaluated else None,
        "recall_at_k": source_recall_total / evaluated if evaluated else None,
        "mean_context_precision": context_precision_total / evaluated if evaluated else None,
        "failure_count": len(failures), "failures": failures,
        "success_rate": (evaluated - len(failures)) / evaluated if evaluated else None,
        "latency_ms": _latency_summary(latencies_ms),
        "retrieval_config": {
            "reranker_model": settings.reranker_model
            if retriever == "reranked" else None,
            "candidate_count": (candidate_count or settings.reranker_candidate_count)
            if retriever in {"hybrid", "reranked"} else None,
            "top_k": top_k,
        },
    }

    if evaluated == 0:
        print("No answerable cases to evaluate.")
        return report
        
    print(f"Hit@{top_k}: {hits / evaluated:.1%} ({hits}/{evaluated})")
     
    print(f"MRR@{top_k}: {report['mrr']:.4f}")

    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval against the golden dataset."
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        choices=range(1, 21),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save the evaluation report as JSON.",
    )

    parser.add_argument(
        "--retriever",
        choices=["vector", "bm25", "keyword", "hybrid", "reranked"],
        default="vector",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        choices=range(3, 101),
        help="Candidate count for hybrid and reranked retrieval.",
    )
    parser.add_argument("--split", choices=["development", "test"], default="development")
    args = parser.parse_args()
    report = run_retrieval_evaluation(
        top_k=args.top_k,
        retriever=args.retriever,
        candidate_count=args.candidate_count,
        split=args.split,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Report saved to {args.output}")
