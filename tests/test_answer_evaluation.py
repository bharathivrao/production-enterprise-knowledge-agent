from unittest.mock import patch

import pytest

from app.evaluation import answer_runner


@pytest.mark.parametrize(
    "answerable,answer,page,expected_abstention,expected_sources",
    [
        (True, "Supported answer [S1].", 2, True, True),
        (True, "Wrong source [S1].", 3, True, False),
        (False, "Invented answer [S1].", 2, False, False),
        (
            False,
            "The available documents do not contain enough information.",
            None,
            True,
            True,
        ),
    ],
)
def test_answer_evaluation_checks(
    answerable,
    answer,
    page,
    expected_abstention,
    expected_sources,
):
    case = {
        "id": "example",
        "question": "Example question",
        "answerable": answerable,
        "expected_answer": "Expected answer",
        "relevant_documents": ["sample.pdf"] if answerable else [],
        "relevant_pages": [2] if answerable else [],
    }

    citations = (
        [{"source_id": "S1", "document": "sample.pdf", "page": page}]
        if page is not None
        else []
    )

    with patch.object(
        answer_runner,
        "answer_question",
        return_value={"answer": answer, "citations": citations},
    ):
        result = answer_runner.evaluate_answer_case(case)

    assert result["abstention_matches"] is expected_abstention
    assert result["citation_sources_match"] is expected_sources


def test_clarification_counts_as_expected_behavior_without_citations():
    case = {
        "id": "ambiguous", "question": "What should I do next?",
        "answerable": False,
        "expected_behavior": "clarify",
        "expected_answer": "Ask what goal or situation the user means.",
        "relevant_documents": [], "relevant_pages": [],
    }
    with patch.object(
        answer_runner,
        "answer_question",
        return_value={"answer": "What goal or situation do you mean?", "citations": []},
    ):
        result = answer_runner.evaluate_answer_case(case)

    assert result["abstention_matches"] is True
    assert result["citation_sources_match"] is True


def test_clarification_with_evidence_citation_does_not_match():
    assert answer_runner._behavior_matches(
        "What goal do you mean?", [{"source_id": "S1"}], "clarify",
    ) is False
