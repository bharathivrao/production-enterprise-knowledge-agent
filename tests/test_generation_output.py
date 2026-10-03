from app.generation.output import extract_final_answer


def test_plain_answer_is_preserved():
    assert extract_final_answer("Answer [S1].") == "Answer [S1]."


def test_thinking_text_is_removed():
    raw = "<think>Considering sources [S2] and [S3].</think>\nAnswer [S1]."

    assert extract_final_answer(raw) == "Answer [S1]."


def test_missing_opening_tag_is_supported():
    raw = "Considering source [S2].</think>\nAnswer [S1]."

    assert extract_final_answer(raw) == "Answer [S1]."


def test_abstention_is_extracted():
    raw = (
        "Considering source [S1].</think>\n"
        "The available documents do not contain enough information."
    )

    assert extract_final_answer(raw) == (
        "The available documents do not contain enough information."
    )