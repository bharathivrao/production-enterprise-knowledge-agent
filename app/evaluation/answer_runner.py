import json
from pathlib import Path

from app.generation.pipeline import answer_question

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def evaluate_answer_case(case: dict, top_k: int = 3) -> dict:
    response = answer_question(case["question"], top_k=top_k)

    abstention = "The available documents do not contain enough information."

    actual_abstention = response["answer"].strip() == abstention

    expected_sources = set(zip(
        case["relevant_documents"],
        case["relevant_pages"],
        strict=True,
    ))

    cited_sources = {
        (citation["document"], citation["page"])
        for citation in response["citations"]
    }

    abstention_matches = actual_abstention == (not case["answerable"])

    if case["answerable"]:
        citation_sources_match = (
            bool(cited_sources)
            and cited_sources <= expected_sources
        )
    else:
        citation_sources_match = not response["citations"]
    return {
        "id": case["id"],
        "question": case["question"],
        "answerable": case["answerable"],
        "expected_answer": case["expected_answer"],
        "relevant_documents": case["relevant_documents"],
        "relevant_pages": case["relevant_pages"],
        "actual_answer": response["answer"],
        "citations": response["citations"],
        "abstention_matches": abstention_matches,
        "citation_sources_match": citation_sources_match,
    }


if __name__ == "__main__":
    dataset_path = PROJECT_ROOT / "evals/golden_dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))

    results = []

    for case in dataset:
        result = evaluate_answer_case(case)
        results.append(result)

        print(
            f"{result['id']} | "
            f"Abstention: {result['abstention_matches']} | "
            f"Sources: {result['citation_sources_match']}"
        )

    report = {
        "evaluated": len(results),
        "abstention_matches": sum(
            result["abstention_matches"] for result in results
        ),
        "citation_sources_match": sum(
            result["citation_sources_match"] for result in results
        ),
        "cases": results,
    }

    output_path = (
        PROJECT_ROOT / "evals/results/answer-abstention-expanded.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Report saved to {output_path}")

