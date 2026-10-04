from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.agents.workflow import WorkflowCitation
from app.memory.conversation_memory import SessionSnapshot, StoredTurn
from app.memory.session_workflow import SessionBudgetExceeded, answer_in_session
from app.memory.working_memory import FollowupResolution
from app.retrieval.scope import RetrievalScope


SESSION_ID, TURN_ID = uuid4(), uuid4()
NOW = datetime.now(timezone.utc)
SCOPE = RetrievalScope(tenant_id="acme", principals=("staff",))


def _snapshot(with_history=True):
    turns = [StoredTurn(
        turn_id=uuid4(), turn_index=1,
        user_question="Who responds to payment incidents?",
        resolved_question="Who responds to payment incidents?",
        answer="UNVERIFIED PRIOR ANSWER",
        citations=[{"source_id": "S1", "document": "payment-incident-runbook.md",
                    "page": None}],
        state="completed", created_at=NOW,
    )] if with_history else []
    return SessionSnapshot(
        session_id=SESSION_ID, version=len(turns), created_at=NOW,
        expires_at=NOW + timedelta(hours=1), turns=turns,
    )


def _workflow():
    return SimpleNamespace(
        state="completed", answer="Mercury owns payments. [S1]",
        citations=[WorkflowCitation(
            source_id="S1", document="service-ownership.md", page=None,
        )],
        trace=[], goal=None, plan=None, metadata=None,
        usage=SimpleNamespace(model_calls=6, tokens=500),
    )


def test_followup_retrieves_fresh_evidence_under_current_scope():
    history = [{"user_question": "Who responds to payment incidents?",
                "cited_source_titles": ["payment-incident-runbook.md"]}]
    with (
        patch("app.memory.session_workflow.load_session", return_value=_snapshot()),
        patch("app.memory.session_workflow.visible_source_titles",
              return_value={"payment-incident-runbook.md"}),
        patch("app.memory.session_workflow.select_history", return_value=history),
        patch("app.memory.session_workflow.resolve_followup", return_value=(
            FollowupResolution(
                needs_clarification=False,
                standalone_question="Who owns the payments platform?",
                clarification_question=None,
            ),
            {"prompt_tokens": 50, "completion_tokens": 10},
        )) as resolver,
        patch("app.memory.session_workflow.run_tool_answer", return_value=_workflow()) as run,
        patch("app.memory.session_workflow.append_turn", return_value=TURN_ID) as append,
    ):
        result = answer_in_session(
            SESSION_ID, "token", "Who owns that service?", scope=SCOPE,
        )
    assert result.resolved_question == (
        "According to the available documents, Who owns the payments platform?"
    )
    assert result.citations[0].document == "service-ownership.md"
    assert result.usage.model_calls == 7
    resolver.assert_called_once_with("Who owns that service?", history)
    run.assert_called_once_with(
        "According to the available documents, Who owns the payments platform?",
        top_k=3, scope=SCOPE,
    )
    assert append.call_args.kwargs["expected_version"] == 1
    assert append.call_args.kwargs["scope"] is SCOPE
    assert "UNVERIFIED PRIOR ANSWER" not in str(resolver.call_args)


def test_ambiguous_followup_clarifies_without_search_or_tools():
    with (
        patch("app.memory.session_workflow.load_session", return_value=_snapshot()),
        patch("app.memory.session_workflow.visible_source_titles", return_value=set()),
        patch("app.memory.session_workflow.select_history", return_value=[{"user_question": "x"}]),
        patch("app.memory.session_workflow.resolve_followup", return_value=(
            FollowupResolution(
                needs_clarification=True,
                standalone_question=None,
                clarification_question="Which service do you mean?",
            ),
            {"prompt_tokens": 30, "completion_tokens": 10},
        )),
        patch("app.memory.session_workflow.run_tool_answer") as run,
        patch("app.memory.session_workflow.append_turn", return_value=TURN_ID) as append,
    ):
        result = answer_in_session(SESSION_ID, "token", "Who owns it?", scope=SCOPE)
    assert result.state == "clarification"
    assert result.citations == []
    assert result.memory.unresolved_questions == ["Which service do you mean?"]
    run.assert_not_called()
    assert append.call_args.kwargs["state"] == "clarification"


def test_combined_budget_blocks_persistence():
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"session_max_model_calls": 6})
    with (
        patch("app.memory.session_workflow.get_settings", return_value=settings),
        patch("app.memory.session_workflow.load_session", return_value=_snapshot()),
        patch("app.memory.session_workflow.visible_source_titles", return_value=set()),
        patch("app.memory.session_workflow.select_history", return_value=[{"user_question": "x"}]),
        patch("app.memory.session_workflow.resolve_followup", return_value=(
            FollowupResolution(needs_clarification=False, standalone_question="Who owns it?",
                               clarification_question=None),
            {"prompt_tokens": 10, "completion_tokens": 10},
        )),
        patch("app.memory.session_workflow.run_tool_answer", return_value=_workflow()),
        patch("app.memory.session_workflow.append_turn") as append,
    ):
        with pytest.raises(SessionBudgetExceeded):
            answer_in_session(SESSION_ID, "token", "Who owns it?", scope=SCOPE)
    append.assert_not_called()
