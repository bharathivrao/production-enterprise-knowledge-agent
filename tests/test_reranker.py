from types import SimpleNamespace
from unittest.mock import patch

from app.retrieval.reranker import deduplicate_candidates, rerank_candidates


def candidate(chunk_id, content, document="policy.md"):
    return {
        "chunk_id": chunk_id,
        "document": document,
        "page": None,
        "content": content,
    }


class FakeScorer:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs, *, batch_size, show_progress_bar):
        self.pairs = pairs
        return self.scores


def test_cross_encoder_scores_query_passage_pairs_and_reorders():
    scorer = FakeScorer([0.2, 0.9])
    with patch(
        "app.retrieval.reranker.get_settings",
        return_value=SimpleNamespace(reranker_min_score=0.05, reranker_batch_size=8),
    ):
        results = rerank_candidates(
            "Who owns payments?",
            [candidate("A", "General policy"), candidate("B", "Mercury owns payments")],
            top_k=2,
            scorer=scorer,
        )
    assert [result["chunk_id"] for result in results] == ["B", "A"]
    assert scorer.pairs[1] == ("Who owns payments?", "Mercury owns payments")


def test_weak_candidates_are_removed():
    with patch(
        "app.retrieval.reranker.get_settings",
        return_value=SimpleNamespace(reranker_min_score=0.5, reranker_batch_size=8),
    ):
        results = rerank_candidates(
            "question", [candidate("A", "weak")], scorer=FakeScorer([0.2])
        )
    assert results == []


def test_duplicate_evidence_is_scored_once_with_provenance_retained():
    unique = deduplicate_candidates([
        candidate("A", "Same   Evidence", "a.md"),
        candidate("B", "same evidence", "b.md"),
    ])
    assert len(unique) == 1
    assert unique[0]["duplicate_sources"] == [{
        "document": "b.md", "page": None, "section": None,
    }]
