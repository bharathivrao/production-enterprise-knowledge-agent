from app.generation.citations import validate_citations
from app.generation.context_builder import build_context
from app.generation.generator import generate_answer
from app.retrieval.bm25 import search_keyword
from app.retrieval.hybrid import search_hybrid
from app.retrieval.reranker import deduplicate_candidates, search_reranked
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope
from app.retrieval.vector_search import search_chunks
from app.generation.output import extract_final_answer
from time import perf_counter
import re


def _is_citation_free_clarification(answer: str) -> bool:
    normalized = answer.strip()
    if (
        re.search(r"\[S\d+\]", normalized)
        or not normalized.endswith("?")
        or "\n" in normalized
        or "." in normalized
        or "!" in normalized
    ):
        return False
    if len(normalized.split()) > 24:
        return False
    return bool(re.match(
        r"(?i)^(what|which|who|where|when|why|how|could you|can you|would you|"
        r"please clarify)\b",
        normalized,
    ))

def answer_question(
    question,
    top_k=5,
    *,
    retriever="vector",
    scope: RetrievalScope = PUBLIC_SCOPE,
    include_diagnostics=False,
):
    searches = {
        "vector": search_chunks,
        "keyword": search_keyword,
        "hybrid": search_hybrid,
        "reranked": search_reranked,
    }
    try:
        search = searches[retriever]
    except KeyError as error:
        raise ValueError(f"Unknown retriever: {retriever}") from error

    started = perf_counter()
    results = search(question, top_k=top_k, scope=scope)
    retrieval_ms = (perf_counter() - started) * 1000
    results = deduplicate_candidates(results)

    if not results:
        response = {
            "answer": "The available documents do not contain enough information.",
            "citations": [],
        }
        if include_diagnostics:
            response["_diagnostics"] = {
                "retrieval_ms": retrieval_ms, "generation_ms": 0.0,
                "total_ms": retrieval_ms, "prompt_tokens": 0,
                "completion_tokens": 0, "context_tokens": 0,
                "retrieved": [], "context": "",
            }
        return response

    evidence = build_context(results)

    generation_started = perf_counter()
    if include_diagnostics:
        generated = generate_answer(
            question, evidence["context"], include_usage=True,
        )
        raw_answer = generated["text"]
    else:
        generated = None
        raw_answer = generate_answer(question, evidence["context"])
    generation_ms = (perf_counter() - generation_started) * 1000
    answer = extract_final_answer(raw_answer)
    if _is_citation_free_clarification(answer):
        citations = []
    else:
        citations = validate_citations(answer, evidence["sources"])

    response = {
        "answer": answer,
        "citations": citations,
    }
    if include_diagnostics:
        response["_diagnostics"] = {
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "total_ms": retrieval_ms + generation_ms,
            "prompt_tokens": generated["prompt_tokens"],
            "completion_tokens": generated["completion_tokens"],
            "context_tokens": evidence["token_count"],
            "model_duration_ms": generated["total_duration_ns"] / 1_000_000,
            "model_load_ms": generated["load_duration_ns"] / 1_000_000,
            "retrieved": results,
            "context": evidence["context"],
        }
    return response
