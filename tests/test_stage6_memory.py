from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.memory.conversation_memory import StoredTurn
from app.memory.working_memory import (
    FollowupResolution, InvalidFollowup, select_history,
)


def _turn(question: str, answer: str, index: int) -> StoredTurn:
    return StoredTurn(
        turn_id=uuid4(), turn_index=index, user_question=question,
        resolved_question=question, answer=answer,
        citations=[{"source_id": "S1", "document": "service-ownership.md",
                    "page": None}],
        state="completed", created_at=datetime.now(timezone.utc),
    )


def test_history_selection_never_sends_prior_generated_answer():
    turns = [
        _turn("Who owns the payments platform?", "UNVERIFIED SECRET ANSWER", 1),
        _turn("What does the ownership guide say?", "PRIVATE GENERATED TEXT", 2),
    ]
    selected = select_history(turns, visible_titles={"service-ownership.md"})
    assert len(selected) == 2
    assert selected[0]["user_question"] == "Who owns the payments platform?"
    assert selected[0]["cited_source_titles"] == ["service-ownership.md"]
    assert "UNVERIFIED SECRET ANSWER" not in str(selected)
    assert "PRIVATE GENERATED TEXT" not in str(selected)
    assert "resolved_question" not in str(selected)


def test_history_is_bounded_by_turns_and_tokens():
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={
        "session_history_turns": 2, "session_history_tokens": 128,
    })
    with patch("app.memory.working_memory.get_settings", return_value=settings):
        selected = select_history([
            _turn("old context", "answer", 1),
            _turn("recent context", "answer", 2),
            _turn("latest context", "answer", 3),
        ], visible_titles={"service-ownership.md"})
    assert [entry["user_question"] for entry in selected] == [
        "recent context", "latest context",
    ]


def test_newly_hidden_source_title_is_removed_from_context():
    selected = select_history(
        [_turn("Who owns the service?", "unverified answer", 1)],
        visible_titles=set(),
    )
    assert selected[0]["cited_source_titles"] == []


def test_resolution_requires_standalone_question_or_clarification():
    assert FollowupResolution(
        needs_clarification=False, standalone_question="Who owns payments?",
        clarification_question=None,
    ).standalone_question
    with pytest.raises(ValueError):
        FollowupResolution(
            needs_clarification=True, standalone_question=None,
            clarification_question="Which service",
        )
    with pytest.raises(ValueError):
        FollowupResolution(needs_clarification=False)


def test_resolver_rejects_malformed_model_output():
    from app.memory.working_memory import resolve_followup

    with patch("app.memory.working_memory.model_client.chat", return_value={
        "message": {"content": '{"needs_clarification":false,"standalone_question":null}'},
    }):
        with pytest.raises(InvalidFollowup):
            resolve_followup("Who owns it?", [{"user_question": "payments platform"}])
