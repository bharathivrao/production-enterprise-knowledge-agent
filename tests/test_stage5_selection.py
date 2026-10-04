from uuid import uuid4

import pytest

from app.agents.tool_selector import InvalidToolChoice, ToolChoice, validate_tool_choice


def test_read_choice_must_use_scoped_candidate_ids_and_cover_named_documents():
    first, second = uuid4(), uuid4()
    candidates = [
        {"chunk_id": str(first), "document": "incident.md", "preview": "on call"},
        {"chunk_id": str(second), "document": "ownership.md", "preview": "Mercury"},
    ]
    choice = ToolChoice(tool="read_document_chunks", chunk_ids=[first, second])
    assert validate_tool_choice(
        choice, candidates, required_documents={"incident.md", "ownership.md"},
    ) is choice
    with pytest.raises(InvalidToolChoice, match="missed"):
        validate_tool_choice(
            ToolChoice(tool="read_document_chunks", chunk_ids=[first]),
            candidates, required_documents={"incident.md", "ownership.md"},
        )
    with pytest.raises(InvalidToolChoice, match="unknown"):
        validate_tool_choice(
            ToolChoice(tool="read_document_chunks", chunk_ids=[uuid4()]),
            candidates, required_documents=set(),
        )


def test_finish_only_when_no_scoped_candidates():
    choice = ToolChoice(tool="finish", chunk_ids=[])
    assert validate_tool_choice(choice, [], required_documents=set()) is choice
    with pytest.raises(InvalidToolChoice):
        validate_tool_choice(
            choice, [{"chunk_id": str(uuid4()), "document": "runbook.md"}],
            required_documents=set(),
        )


def test_schema_excludes_arbitrary_tool_names():
    with pytest.raises(ValueError):
        ToolChoice(tool="delete_document", chunk_ids=[])
