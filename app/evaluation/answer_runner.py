import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from app.core.config import get_settings
from app.evaluation.dataset import GoldenCase, load_dataset
from app.evaluation.generation import GRADER_PROMPT_VERSION, grade_answer
from app.evaluation.runner import _latency_summary
from app.generation.generator import ANSWER_PROMPT_VERSION, ANSWER_SYSTEM_PROMPT
from app.generation.pipeline import answer_question


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ABSTENTION = "The available documents do not contain enough information."


def _expected_sources(case) -> set[tuple[str, int | None]]:
    if isinstance(case, GoldenCase):
        return case.expected_sources
    return set(zip(case["relevant_documents"], case["relevant_pages"], strict=True))


def _expected_behavior(data: dict) -> str:
    return data.get("expected_behavior") or (
        "answer" if data["answerable"] else "abstain"
    )


def _behavior_matches(answer: str, citations: list[dict], behavior: str) -> bool:
    normalized = answer.strip()
    if behavior == "answer":
        return normalized != ABSTENTION and bool(citations)
    if behavior == "abstain":
        return normalized == ABSTENTION and not citations
    if behavior == "clarify":
        return not citations and bool(re.search(r"\?\s*$", normalized))
    raise ValueError(f"Unknown expected answer behavior: {behavior}")


def evaluate_answer_case(case: dict | GoldenCase, top_k: int = 3, *, grade=False) -> dict:
    data = case.model_dump() if isinstance(case, GoldenCase) else case
    response = answer_question(
        data["question"], top_k=top_k, include_diagnostics=True,
    ) if grade else answer_question(data["question"], top_k=top_k)

    behavior = _expected_behavior(data)
    expected_sources = _expected_sources(case)
    cited_sources = {
        (citation["document"], citation["page"])
        for citation in response["citations"]
    }
    abstention_matches = _behavior_matches(
        response["answer"], response["citations"], behavior,
    )
    citation_sources_match = (
        bool(cited_sources) and cited_sources <= expected_sources
        if data["answerable"]
        else not response["citations"]
    )
    result = {
        "id": data["id"], "question": data["question"],
        "answerable": data["answerable"], "expected_answer": data["expected_answer"],
        "expected_behavior": behavior,
        "relevant_documents": data["relevant_documents"],
        "relevant_pages": data["relevant_pages"],
        "actual_answer": response["answer"], "citations": response["citations"],
        "abstention_matches": abstention_matches,
        "citation_sources_match": citation_sources_match,
    }
    if grade:
        diagnostics = response["_diagnostics"]
        judged, judge_usage = grade_answer(
            question=data["question"], expected_answer=data["expected_answer"],
            actual_answer=response["answer"], evidence=diagnostics["context"],
        )
        result.update({
            "scores": {
                "factual_correctness": judged.factual_correctness,
                "completeness": judged.completeness,
                "faithfulness": judged.faithfulness,
                "answer_relevance": judged.answer_relevance,
                "claim_citation_support": judged.claim_citation_support,
            },
            "claim_assessments": [claim.model_dump() for claim in judged.claims],
            "grader_rationale": judged.rationale,
            "usage": {
                "answer_prompt_tokens": diagnostics["prompt_tokens"],
                "answer_completion_tokens": diagnostics["completion_tokens"],
                "grader_prompt_tokens": judge_usage["prompt_tokens"],
                "grader_completion_tokens": judge_usage["completion_tokens"],
                "context_tokens": diagnostics["context_tokens"],
                "estimated_cost_usd": 0.0,
                "pricing_basis": "local models; no per-token API charge",
            },
            "latency_ms": {
                "retrieval": diagnostics["retrieval_ms"],
                "generation": diagnostics["generation_ms"],
                "grader": judge_usage["duration_ms"],
                "total": diagnostics["total_ms"] + judge_usage["duration_ms"],
            },
        })
    return result


def _atomic_json_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_answer_evaluation(*, split="development", top_k=3, output_path=None):
    bundle = load_dataset(PROJECT_ROOT, split=split)
    results = []
    failures = []
    for case in bundle.cases:
        try:
            result = evaluate_answer_case(case, top_k=top_k, grade=True)
            results.append(result)
            print(f"{case.id}: scored", flush=True)
        except Exception as error:
            failure = {
                "id": case.id, "error_type": type(error).__name__,
                "error": str(error),
            }
            failures.append(failure)
            print(f"{case.id}: ERROR {type(error).__name__}", flush=True)

        if output_path is not None:
            _atomic_json_write(
                output_path,
                _build_report(bundle, results, failures, top_k, partial=True),
            )
    report = _build_report(bundle, results, failures, top_k, partial=False)
    if output_path is not None:
        _atomic_json_write(output_path, report)
    return report


def _build_report(bundle, results, failures, top_k, *, partial):
    score_names = (
        "factual_correctness", "completeness", "faithfulness",
        "answer_relevance", "claim_citation_support",
    )
    settings = get_settings()
    return {
        "report_version": "3.0.0", "partial": partial,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": bundle.split, "dataset_version": bundle.manifest.dataset_version,
        "dataset_sha256": bundle.dataset_sha256,
        "corpus_version": bundle.manifest.corpus_version,
        "corpus_sha256": bundle.corpus_sha256,
        "prompt_version": ANSWER_PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(ANSWER_SYSTEM_PROMPT.encode()).hexdigest(),
        "grader_prompt_version": GRADER_PROMPT_VERSION,
        "models": {
            "embedding": settings.embedding_model,
            "generation": settings.generation_model,
            "grader": settings.evaluation_model,
        },
        "retrieval": {"name": "vector", "top_k": top_k},
        "expected_cases": len(bundle.cases), "completed_cases": len(results),
        "failure_count": len(failures), "failures": failures,
        "metrics": {
            **{
                name: mean(result["scores"][name] for result in results) if results else None
                for name in score_names
            },
            "abstention_accuracy": (
                mean(result["abstention_matches"] for result in results) if results else None
            ),
            "citation_source_accuracy": (
                mean(result["citation_sources_match"] for result in results) if results else None
            ),
            "success_rate": len(results) / len(bundle.cases) if bundle.cases else None,
        },
        "latency_ms": {
            name: _latency_summary([result["latency_ms"][name] for result in results])
            for name in ("retrieval", "generation", "grader", "total")
        } | {
            "answer_total": _latency_summary([
                result["latency_ms"]["retrieval"] + result["latency_ms"]["generation"]
                for result in results
            ])
        },
        "tokens": {
            key: sum(result["usage"][key] for result in results)
            for key in (
                "answer_prompt_tokens", "answer_completion_tokens",
                "grader_prompt_tokens", "grader_completion_tokens", "context_tokens",
            )
        },
        "estimated_cost_usd": 0.0,
        "cases": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate grounded answer quality.")
    parser.add_argument("--split", choices=["development", "test"], default="development")
    parser.add_argument("--top-k", type=int, default=3, choices=range(1, 21))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_answer_evaluation(split=args.split, top_k=args.top_k, output_path=args.output)
