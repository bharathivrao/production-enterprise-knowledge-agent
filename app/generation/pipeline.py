from app.generation.citations import validate_citations
from app.generation.context_builder import build_context
from app.generation.generator import generate_answer
from app.retrieval.bm25 import search_keyword
from app.retrieval.hybrid import search_hybrid
from app.retrieval.reranker import deduplicate_candidates, search_reranked
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope
from app.retrieval.vector_search import search_chunks
from app.generation.output import extract_final_answer

def answer_question(
    question,
    top_k=5,
    *,
    retriever="vector",
    scope: RetrievalScope = PUBLIC_SCOPE,
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

    results = search(question, top_k=top_k, scope=scope)
    results = deduplicate_candidates(results)

    if not results:
        return {
            "answer": "The available documents do not contain enough information.",
            "citations": [],
        }

    evidence = build_context(results)

    raw_answer = generate_answer(question, evidence["context"])
    answer = extract_final_answer(raw_answer)
    citations = validate_citations(answer, evidence["sources"])

    return {
        "answer": answer,
        "citations": citations,
    }
