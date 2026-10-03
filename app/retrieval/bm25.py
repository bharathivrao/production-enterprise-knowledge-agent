import re

from rank_bm25 import BM25Okapi

from app.db.repository import load_search_chunks


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by",
    "can", "do", "for", "from", "get", "how", "i", "in",
    "is", "it", "me", "my", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "what", "with",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"\w+", text.lower())
    return [word for word in words if word not in STOP_WORDS]


def search_bm25(query: str, top_k: int = 5) -> list[dict]:
    if not query.strip():
        raise ValueError("query must not be blank")

    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")

    query_tokens = tokenize(query)
    chunks = load_search_chunks()

    if not chunks or not query_tokens:
        return []

    tokenized_chunks = [
        tokenize(chunk["content"]) for chunk in chunks
    ]

    if not any(tokenized_chunks):
        return []

    bm25 = BM25Okapi(tokenized_chunks)
    scores = bm25.get_scores(query_tokens)

    ranked_indices = sorted(
        range(len(chunks)),
        key=lambda index: scores[index],
        reverse=True,
    )

    return [
        {
            **chunks[index],
            "bm25_score": float(scores[index]),
        }
        for index in ranked_indices[:top_k]
    ]