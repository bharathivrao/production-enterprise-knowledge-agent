import json
from unittest.mock import patch
import hashlib
from app.evaluation import runner
from types import SimpleNamespace

def test_retrieval_evaluation_counts_hit_and_miss(tmp_path, capsys):
    dataset = [
        {
            "id": "correct-page",
            "question": "First question",
            "answerable": True,
            "relevant_documents": ["sample.pdf"],
            "relevant_pages": [1],
        },
        {
            "id": "wrong-page",
            "question": "Second question",
            "answerable": True,
            "relevant_documents": ["sample.pdf"],
            "relevant_pages": [2],
        },
        {
            "id": "unanswerable",
            "question": "Unsupported question",
            "answerable": False,
            "relevant_documents": [],
            "relevant_pages": [],
        },
    ]

    directory = tmp_path / "evals"
    directory.mkdir()
    (directory / "golden_dataset.json").write_text(
        json.dumps(dataset),
        encoding="utf-8",
    )

    with (
        patch.object(runner, "PROJECT_ROOT", tmp_path),
        patch.object(
            runner,
            "search_chunks",
            side_effect=[
                [{"document": "sample.pdf", "page": 1, "distance": 0.2}],
                [{"document": "sample.pdf", "page": 3, "distance": 0.7}],
            ],
        ) as search,
        patch.object(
            runner,
            "get_settings",
            return_value=SimpleNamespace(embedding_model="test-model"),
        ),
    ):
    
        report = runner.run_retrieval_evaluation(top_k=3)

    assert report["hit_rate"] == 0.5
    assert report["evaluated"] == 2
    assert report["skipped_unanswerable"] == 1
    assert report["embedding_model"] == "test-model"
    assert report["dataset_sha256"] == hashlib.sha256(
        (directory / "golden_dataset.json").read_bytes()
    ).hexdigest()

    assert report["mrr"] == 0.5
    assert report["cases"][0]["first_relevant_rank"] == 1
    assert report["cases"][1]["first_relevant_rank"] is None
    
    output = capsys.readouterr().out

    assert "correct-page: HIT" in output
    assert "wrong-page: MISS" in output
    assert "Hit@3: 50.0% (1/2)" in output
    assert search.call_count == 2

def test_no_answerable_cases_returns_unscored_report(tmp_path, capsys):
    dataset = [
        {
            "id": "unsupported",
            "question": "A question without supporting evidence",
            "answerable": False,
            "relevant_documents": [],
            "relevant_pages": [],
        }
    ]

    directory = tmp_path / "evals"
    directory.mkdir()
    (directory / "golden_dataset.json").write_text(
        json.dumps(dataset),
        encoding="utf-8",
    )

    with (
        patch.object(runner, "PROJECT_ROOT", tmp_path),
        patch.object(runner, "search_chunks") as search,
        patch.object(
            runner,
            "get_settings",
            return_value=SimpleNamespace(embedding_model="test-model"),
        ),
    ):
        report = runner.run_retrieval_evaluation(top_k=3)

    assert report["evaluated"] == 0
    assert report["hit_rate"] is None
    assert report["cases"] == []
    assert report["skipped_unanswerable"] == 1

    search.assert_not_called()

    assert "No answerable cases to evaluate." in capsys.readouterr().out