from app.retrieval.bm25 import search_bm25
from app.retrieval.vector_search import search_chunks

def reciprocal_rank_fusion(
    ranked_lists: list[list[dict]],
    top_k: int = 5,
    rank_constant: int = 60,
) -> list[dict]:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")

    chunks = {}
    scores = {}

    for results in ranked_lists:
        seen = set()

        for rank, result in enumerate(results, start=1):
            chunk_id = result["chunk_id"]

            if chunk_id in seen:
                continue

            seen.add(chunk_id)
            chunks.setdefault(chunk_id, result)
            scores[chunk_id] = (
                scores.get(chunk_id, 0.0)
                + 1 / (rank_constant + rank)
            )

    ranked_ids = sorted(
        scores,
        key=lambda chunk_id: (-scores[chunk_id], chunk_id),
    )

    fused = []
    for chunk_id in ranked_ids[:top_k]:
        result = {
            "chunk_id": chunk_id,
            "document": chunks[chunk_id]["document"],
            "page": chunks[chunk_id]["page"],
            "content": chunks[chunk_id]["content"],
            "rrf_score": scores[chunk_id],
        }
        if chunks[chunk_id].get("section") is not None:
            result["section"] = chunks[chunk_id]["section"]
        fused.append(result)
    return fused

def search_hybrid(query: str, top_k: int = 5) -> list[dict]:
    if not query.strip():
        raise ValueError("query must not be blank")

    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    candidate_k = min(20, max(10, top_k))

    vector_results = search_chunks(query, top_k=candidate_k)
    bm25_results = search_bm25(query, top_k=candidate_k)

    matching_bm25_results = [
        result
        for result in bm25_results
        if result["bm25_score"] > 0
    ]

    return reciprocal_rank_fusion(
        [vector_results, matching_bm25_results],
        top_k=top_k,
    )
