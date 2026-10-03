import pytest

from app.retrieval.hybrid import reciprocal_rank_fusion


def make_chunk(chunk_id):
    return {
        "chunk_id": chunk_id,
        "document": "example.pdf",
        "page": 1,
        "content": f"Content for {chunk_id}",
    }


def test_shared_chunk_gets_both_rank_contributions():
    vector_results = [make_chunk("A"), make_chunk("B")]
    bm25_results = [make_chunk("B"), make_chunk("C")]

    results = reciprocal_rank_fusion(
        [vector_results, bm25_results],
        top_k=3,
    )

    assert [result["chunk_id"] for result in results] == ["B", "A", "C"]
    assert results[0]["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)


def test_duplicate_in_one_list_does_not_add_points():
    results = reciprocal_rank_fusion(
        [[make_chunk("A"), make_chunk("A")]],
    )

    assert len(results) == 1
    assert results[0]["rrf_score"] == pytest.approx(1 / 61)


def test_empty_rankings_return_no_results():
    assert reciprocal_rank_fusion([[], []]) == []