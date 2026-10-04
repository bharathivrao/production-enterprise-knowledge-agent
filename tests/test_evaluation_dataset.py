import json

import pytest

from app.evaluation.dataset import load_dataset


def test_dataset_has_disjoint_versioned_splits():
    bundle = load_dataset(__import__("pathlib").Path(__file__).resolve().parents[1], split="all")
    manifest = bundle.manifest
    assert len(bundle.cases) == 50
    assert set(manifest.development_ids).isdisjoint(manifest.test_ids)
    assert len(manifest.test_ids) == 15
    assert bundle.dataset_sha256
    assert bundle.corpus_sha256
    ambiguous = next(case for case in bundle.cases if case.id == "ambiguous-what-should-i-do")
    assert ambiguous.expected_behavior == "clarify"


def test_dataset_rejects_source_length_mismatch(tmp_path):
    evals = tmp_path / "evals"
    evals.mkdir()
    (tmp_path / "data/raw").mkdir(parents=True)
    (evals / "golden_dataset.json").write_text(json.dumps([{
        "id": "bad", "question": "q", "answerable": True,
        "expected_answer": "a", "relevant_documents": ["a", "b"],
        "relevant_pages": [1],
    }]))
    with pytest.raises(ValueError):
        load_dataset(tmp_path)
