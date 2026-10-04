import argparse
import json
from pathlib import Path
from statistics import mean

from app.evaluation.dataset import load_dataset
from app.generation.pipeline import answer_question


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _normalize(text):
    return " ".join(text.casefold().split())


def summarize_runs(runs):
    if not runs:
        return {"answer_agreement": 0.0, "citation_agreement": 0.0}
    answers = [_normalize(run["answer"]) for run in runs]
    citations = [
        tuple((item["document"], item.get("page"), item.get("section")) for item in run["citations"])
        for run in runs
    ]
    return {
        "answer_agreement": max(answers.count(value) for value in set(answers)) / len(answers),
        "citation_agreement": max(citations.count(value) for value in set(citations)) / len(citations),
    }


def run_repeatability(*, split="development", runs=3, case_limit=5):
    cases = load_dataset(PROJECT_ROOT, split=split).cases[:case_limit]
    results = []
    for case in cases:
        observations = []
        failures = []
        for run_number in range(1, runs + 1):
            try:
                response = answer_question(case.question, top_k=3)
                observations.append({"run": run_number, **response})
            except Exception as error:
                failures.append({
                    "run": run_number, "error_type": type(error).__name__, "error": str(error),
                })
        results.append({
            "id": case.id, "runs": observations, "failures": failures,
            **summarize_runs(observations),
        })
    return {
        "split": split, "runs_per_case": runs, "case_count": len(cases),
        "answer_agreement": mean(item["answer_agreement"] for item in results),
        "citation_agreement": mean(item["citation_agreement"] for item in results),
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Measure answer variation across repeated runs.")
    parser.add_argument("--split", choices=["development", "test"], default="development")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--case-limit", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_repeatability(split=args.split, runs=args.runs, case_limit=args.case_limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "answer_agreement": report["answer_agreement"],
        "citation_agreement": report["citation_agreement"],
    }, indent=2))
