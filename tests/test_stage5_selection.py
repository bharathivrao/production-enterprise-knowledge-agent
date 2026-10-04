from uuid import uuid4
from unittest.mock import patch

import pytest

from app.agents.tool_selector import InvalidToolChoice, ToolChoice, validate_tool_choice


def test_read_choice_must_use_scoped_candidate_ids_and_cover_named_documents():
    first, second = uuid4(), uuid4()
    candidates = [
        {"chunk_id": str(first), "document": "incident.md", "preview": "on call"},
        {"chunk_id": str(second), "document": "ownership.md", "preview": "Mercury"},
    ]
    choice = ToolChoice(tool="read_document_chunks", candidate_numbers=[1, 2])
    selected = validate_tool_choice(
        choice, candidates, required_documents={"incident.md", "ownership.md"},
    )
    assert selected.chunk_ids == [first, second]
    with pytest.raises(InvalidToolChoice, match="missed"):
        validate_tool_choice(
            ToolChoice(tool="read_document_chunks", candidate_numbers=[1]),
            candidates, required_documents={"incident.md", "ownership.md"},
        )
    with pytest.raises(InvalidToolChoice, match="unknown"):
        validate_tool_choice(
            ToolChoice(tool="read_document_chunks", candidate_numbers=[3]),
            candidates, required_documents=set(),
        )


def test_finish_only_when_no_scoped_candidates():
    choice = ToolChoice(tool="finish", candidate_numbers=[])
    assert validate_tool_choice(choice, [], required_documents=set()).chunk_ids == []
    with pytest.raises(InvalidToolChoice):
        validate_tool_choice(
            choice, [{"chunk_id": str(uuid4()), "document": "runbook.md"}],
            required_documents=set(),
        )


def test_schema_excludes_arbitrary_tool_names():
    with pytest.raises(ValueError):
        ToolChoice(tool="delete_document", candidate_numbers=[])


def test_model_sees_numbered_previews_and_server_maps_to_chunk_ids():
    from app.agents.goal_analyzer import Goal
    from app.agents.tool_selector import select_tool

    chunk_id = uuid4()
    candidates = [{
        "chunk_id": str(chunk_id), "document": "runbook.md",
        "page": None, "section": "Response", "preview": "On-call responds",
    }]
    goal = Goal(
        objective="Find responder", entities=[],
        deliverables=["responder"], constraints=[],
    )
    with patch("app.agents.tool_selector.model_client.chat", return_value={
        "message": {"content": '{"tool":"read_document_chunks","candidate_numbers":[1]}'},
    }) as model:
        selected, _ = select_tool(
            "Who responds?", goal, candidates, required_documents={"runbook.md"},
        )
    assert selected.chunk_ids == [chunk_id]
    prompt = model.call_args.kwargs["messages"][1]["content"]
    assert '"number": 1' in prompt
    assert str(chunk_id) not in prompt
