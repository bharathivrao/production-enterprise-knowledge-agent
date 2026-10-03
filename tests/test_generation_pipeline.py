from unittest.mock import patch

from app.generation import pipeline


def test_pipeline_validates_only_final_answer():
    raw_answer = (
        "Considering another source [S99].</think>\n"
        "The supported answer [S1]."
    )

    with (
        patch.object(
            pipeline,
            "search_chunks",
            return_value=[{
                "document": "sample.pdf",
                "page": 2,
                "content": "Supporting evidence",
                "distance": 0.2,
            }],
        ),
        patch.object(
            pipeline,
            "generate_answer",
            return_value=raw_answer,
        ),
    ):
        result = pipeline.answer_question("A question")

    assert result == {
        "answer": "The supported answer [S1].",
        "citations": [{
            "source_id": "S1",
            "document": "sample.pdf",
            "page": 2,
        }],
    }

def test_pipeline_abstention_has_no_citations():
    raw_answer = (
        "Reviewed evidence [S1].</think>\n"
        "The available documents do not contain enough information."
    )

    with (
        patch.object(
            pipeline,
            "search_chunks",
            return_value=[{
                "document": "settlement-runbook.pdf",
                "page": 1,
                "content": "Retries are limited to three attempts.",
                "distance": 0.3,
            }],
        ),
        patch.object(
            pipeline,
            "generate_answer",
            return_value=raw_answer,
        ),
    ):
        result = pipeline.answer_question("How long should I wait?")

    assert result == {
        "answer": "The available documents do not contain enough information.",
        "citations": [],
    }