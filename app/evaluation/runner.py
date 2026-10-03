import json
from pathlib import Path
import argparse
from app.retrieval.vector_search import search_chunks
import hashlib
from datetime import datetime, timezone
from app.retrieval.bm25 import search_bm25
from app.core.config import get_settings
from app.retrieval.hybrid import search_hybrid

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_retrieval_evaluation(top_k=3, retriever="vector"):
    if retriever == "vector":
        search = search_chunks
        score_field = "distance"
    elif retriever == "bm25":
        search = search_bm25
        score_field = "bm25_score"
    elif retriever == "hybrid":
        search = search_hybrid
        score_field = "rrf_score"
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

    for case in dataset:
        if not case["answerable"]:
            continue

        results = search(case["question"], top_k=top_k)

        expected = set(zip(
            case["relevant_documents"],
            case["relevant_pages"],
            strict=True,
        ))

        retrieved = {
            (result["document"], result["page"])
            for result in results
        }

        hit = bool(expected & retrieved)

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
        evaluated += 1

        cases.append({
            "id": case["id"],
            "hit": hit,
            "first_relevant_rank": first_relevant_rank,
            "reciprocal_rank": reciprocal_rank,     
            "retrieved_sources": [
                {
                    "document": result["document"],
                    "page": result["page"],
                    score_field: result[score_field],
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
            if retriever in {"vector", "hybrid"}
            else None
        ),
        "dataset_sha256": dataset_hash,
        "mrr": reciprocal_rank_total / evaluated if evaluated else None,
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
        choices=["vector", "bm25", "hybrid"],
        default="vector",
    )
    args = parser.parse_args()
    report = run_retrieval_evaluation(
        top_k=args.top_k,
        retriever=args.retriever,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Report saved to {args.output}")
