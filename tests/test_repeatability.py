from app.evaluation.repeatability import summarize_runs


def test_repeatability_normalizes_answer_whitespace_and_case():
    result = summarize_runs([
        {"answer": "Answer [S1].", "citations": [{"document": "a", "page": 1}]},
        {"answer": " answer   [s1]. ", "citations": [{"document": "a", "page": 1}]},
        {"answer": "Different [S1].", "citations": [{"document": "a", "page": 1}]},
    ])
    assert result["answer_agreement"] == 2 / 3
    assert result["citation_agreement"] == 1.0
