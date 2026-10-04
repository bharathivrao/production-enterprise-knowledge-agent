import argparse
import json
from pathlib import Path
from statistics import mean

from app.evaluation.generation import grade_answer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = (
    "factual_correctness", "completeness", "faithfulness", "answer_relevance",
)


def run_calibration(path=None):
    path = path or PROJECT_ROOT / "evals/grader_calibration.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    results = []
    absolute_errors = []
    within_one = []
    for case in cases:
        grade, usage = grade_answer(
            question=case["question"], expected_answer=case["expected_answer"],
            actual_answer=case["actual_answer"], evidence=case["evidence"],
        )
        automated = {name: getattr(grade, name) for name in DIMENSIONS}
        errors = {
            name: abs(automated[name] - case["human_scores"][name])
            for name in DIMENSIONS
        }
        absolute_errors.extend(errors.values())
        within_one.extend(error <= 1 for error in errors.values())
        results.append({
            "id": case["id"], "human_scores": case["human_scores"],
            "automated_scores": automated, "absolute_errors": errors,
            "rationale": grade.rationale, "usage": usage,
        })
    return {
        "cases": len(cases),
        "overall_mean_absolute_error": mean(absolute_errors),
        "within_one_rate": mean(within_one),
        "dimension_mae": {
            name: mean(result["absolute_errors"][name] for result in results)
            for name in DIMENSIONS
        },
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate the answer grader against human labels.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_calibration()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("cases", "overall_mean_absolute_error", "within_one_rate")}, indent=2))
