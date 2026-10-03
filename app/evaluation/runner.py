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

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _latency_summary(values):
    if not values:
        return {"mean": None, "p50": None, "p95": None}
    ordered = sorted(values)

    def percentile(fraction):
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]

    return {"mean": mean(values), "p50": percentile(0.50), "p95": percentile(0.95)}


def run_retrieval_evaluation(top_k=3, retriever="vector", candidate_count=None):
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
    
    dataset_path = PROJECT_ROOT / "evals/golden_dataset.json"
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes)

    dataset_hash = hashlib.sha256(dataset_bytes).hexdigest()
    settings = get_settings()

    hits = 0
    evaluated = 0
    cases = []
    reciprocal_rank_total = 0.0
    full_coverage_count = 0
    source_recall_total = 0.0
    latencies_ms = []

    for case in dataset:
        if not case["answerable"]:
            continue

        started = perf_counter()
        results = search(case["question"], top_k=top_k)
        latency_ms = (perf_counter() - started) * 1000
        latencies_ms.append(latency_ms)

        expected = {
            (item["document"], item.get("page"))
            for item in case.get("relevant_sources", [])
        } or set(zip(
            case["relevant_documents"], case["relevant_pages"], strict=True,
        ))

        retrieved = {
            (result["document"], result["page"])
            for result in results
        }

        hit = bool(expected & retrieved)
        relevant_retrieved = expected & retrieved
        all_relevant_retrieved = expected <= retrieved
        source_recall = len(relevant_retrieved) / len(expected) if expected else 1.0

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
        evaluated += 1

        cases.append({
            "id": case["id"],
            "hit": hit,
            "all_relevant_retrieved": all_relevant_retrieved,
            "source_recall": source_recall,
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

        print(f"{case['id']}: {'HIT' if hit else 'MISS'}")
       

    report = {
        "top_k": top_k,
        "evaluated": evaluated,
        "hits": hits,
        "hit_rate": hits / evaluated if evaluated else None,
        "skipped_unanswerable": sum(
            not case["answerable"] for case in dataset
        ),
        "cases": cases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retriever": retriever,
        "embedding_model": (
            settings.embedding_model
            if retriever in {"vector", "hybrid", "reranked"}
            else None
        ),
        "dataset_sha256": dataset_hash,
        "mrr": reciprocal_rank_total / evaluated if evaluated else None,
        "full_coverage_rate": full_coverage_count / evaluated if evaluated else None,
        "mean_source_recall": source_recall_total / evaluated if evaluated else None,
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
    args = parser.parse_args()
    report = run_retrieval_evaluation(
        top_k=args.top_k,
        retriever=args.retriever,
        candidate_count=args.candidate_count,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Report saved to {args.output}")
