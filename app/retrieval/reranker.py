import hashlib
import threading
from functools import lru_cache
from typing import Protocol, Sequence

from app.core.config import get_settings
from app.retrieval.hybrid import search_hybrid
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope


class PairScorer(Protocol):
    def predict(self, pairs, *, batch_size: int, show_progress_bar: bool): ...


_prediction_lock = threading.Lock()


class RerankerUnavailableError(RuntimeError):
    """Raised when the configured local cross-encoder cannot score candidates."""


@lru_cache(maxsize=1)
def get_cross_encoder():
    # Imported lazily so API startup and liveness do not initialize PyTorch or
    # download a model. Deployment should pre-cache the configured checkpoint.
    import torch
    from sentence_transformers import CrossEncoder

    settings = get_settings()
    return CrossEncoder(
        settings.reranker_model,
        max_length=settings.reranker_max_length,
        activation_fn=torch.nn.Sigmoid(),
    )


def close_reranker() -> None:
    get_cross_encoder.cache_clear()


def _content_key(content: str) -> str:
    normalized = " ".join(content.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deduplicate_candidates(candidates: Sequence[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for candidate in candidates:
        key = _content_key(candidate["content"])
        if key not in unique:
            unique[key] = {**candidate, "duplicate_sources": []}
        else:
            unique[key]["duplicate_sources"].append({
                "document": candidate["document"],
                "page": candidate.get("page"),
                "section": candidate.get("section"),
            })
    return list(unique.values())


def rerank_candidates(
    query: str,
    candidates: Sequence[dict],
    *,
    top_k: int = 5,
    scorer: PairScorer | None = None,
    min_score: float | None = None,
) -> list[dict]:
    if not query.strip():
        raise ValueError("query must not be blank")
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be between 1 and 20")
    if not candidates:
        return []

    settings = get_settings()
    threshold = settings.reranker_min_score if min_score is None else min_score
    unique = deduplicate_candidates(candidates)
    pairs = [(query, candidate["content"]) for candidate in unique]
    try:
        model = scorer or get_cross_encoder()
        with _prediction_lock:
            scores = model.predict(
                pairs,
                batch_size=settings.reranker_batch_size,
                show_progress_bar=False,
            )
    except (OSError, RuntimeError) as error:
        raise RerankerUnavailableError(
            "The cross-encoder reranker could not score candidates."
        ) from error

    scored = [
        {**candidate, "rerank_score": float(score)}
        for candidate, score in zip(unique, scores, strict=True)
        if float(score) >= threshold
    ]
    scored.sort(key=lambda item: (-item["rerank_score"], item["chunk_id"]))
    return scored[:top_k]


def search_reranked(
    query: str,
    top_k: int = 5,
    *,
    candidate_k: int | None = None,
    scope: RetrievalScope = PUBLIC_SCOPE,
    scorer: PairScorer | None = None,
) -> list[dict]:
    settings = get_settings()
    candidate_k = candidate_k or max(settings.reranker_candidate_count, top_k)
    candidates = search_hybrid(
        query,
        top_k=candidate_k,
        candidate_k=candidate_k,
        scope=scope,
    )
    return rerank_candidates(
        query, candidates, top_k=top_k, scorer=scorer,
    )
