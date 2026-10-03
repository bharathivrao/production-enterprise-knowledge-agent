from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.generation.citations import CitationValidationError

client = TestClient(app)


def test_ask_returns_valid_answer():
    expected = {
        "answer": "The formula has six parts [S1].",
        "citations": [
            {
                "source_id": "S1",
                "document": "sample.pdf",
                "page": 1,
            }
        ],
    }

    with patch(
        "app.api.query.answer_question",
        return_value=expected,
    ) as pipeline:
        response = client.post(
            "/ask",
            json={"query": "What is the formula?", "top_k": 3},
        )

    assert response.status_code == 200
    assert response.json() == expected
    pipeline.assert_called_once_with(
        "What is the formula?",
        top_k=3,
    )

def test_ask_with_invalid_input_returns_422():
    
    with patch("app.api.query.answer_question") as pipeline:
        response = client.post(
            "/ask",
            json={"query": " "},
        )

    assert response.status_code == 422
    pipeline.assert_not_called()

def test_ask_with_invalid_citations_returns_502():
    with patch(
        "app.api.query.answer_question",
        side_effect=CitationValidationError("Unknown source"),
    ):
        # Send the request here.
        response = client.post(
            "/ask",
            json={"query": "What is the formula?"},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "The generated answer failed citation validation."}

def test_ask_returns_503_when_model_is_unavailable():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with (
        patch(
            "app.api.query.answer_question",
            side_effect=ConnectionError("Ollama connection failed"),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/ask",
            json={"query": "What is the settlement retry policy?"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The model service is unavailable. Try again later."
    }

def test_search_returns_503_when_model_is_unavailable():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with (
        patch(
            "app.api.query.search_chunks",
            side_effect=ConnectionError("Ollama connection failed"),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/search",
            json={"query": "Settlement retry policy"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The model service is unavailable. Try again later."
    }

def test_ask_returns_504_when_model_times_out():
    import httpx
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import app

    with (
        patch(
            "app.api.query.answer_question",
            side_effect=httpx.ReadTimeout("Model response timed out"),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/ask",
            json={"query": "What is the settlement retry policy?"},
        )

    assert response.status_code == 504
    assert response.json() == {
        "detail": "The model service timed out. Try again later."
    }

def test_ask_returns_502_when_model_is_missing():
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from ollama import ResponseError

    from app.main import app

    with (
        patch(
            "app.api.query.answer_question",
            side_effect=ResponseError(
                "model 'missing-model' not found",
                status_code=404,
            ),
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/ask",
            json={"query": "What is the settlement retry policy?"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The model service could not complete the request."
    }


def test_search_can_select_reranked_retrieval():
    expected = [{
        "chunk_id": "one", "document": "policy.md", "page": None,
        "content": "evidence", "rerank_score": 0.9,
    }]
    with patch("app.api.query.search_reranked", return_value=expected) as search:
        response = client.post(
            "/search",
            json={"query": "policy", "top_k": 3, "retriever": "reranked"},
        )
    assert response.status_code == 200
    assert response.json() == {"results": expected}
    search.assert_called_once_with("policy", 3)


def test_reranker_failure_returns_503():
    from app.retrieval.reranker import RerankerUnavailableError

    with patch(
        "app.api.query.search_reranked",
        side_effect=RerankerUnavailableError("missing checkpoint"),
    ):
        response = client.post(
            "/search",
            json={"query": "policy", "retriever": "reranked"},
        )
    assert response.status_code == 503
