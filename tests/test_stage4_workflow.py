from unittest.mock import patch
from time import perf_counter

import pytest

from app.agents.goal_analyzer import Goal, GoalAnalysis
from app.agents.planner import Plan, SearchStep, SynthesizeStep
from app.agents.synthesizer import Finding, SynthesisDraft
from app.agents.workflow import (
    WorkflowBudgetExceeded, WorkflowRunError, _Budget,
    _restrict_to_named_documents,
    run_planned_answer,
)


QUESTION = "Compare payment incident recovery and platform ownership"
GOAL = Goal(
    objective="Compare payment incident recovery and platform ownership",
    entities=["payment incident", "payments platform"],
    deliverables=["incident recovery", "platform ownership"], constraints=[],
)
PLAN = Plan(goal=GOAL, steps=[
    SearchStep(
        step_id="incident", type="search", purpose="Find incident recovery",
        query="severity one payment recovery", deliverable_index=0,
    ),
    SearchStep(
        step_id="ownership", type="search", purpose="Find platform ownership",
        query="payments platform technical owner", deliverable_index=1,
    ),
    SynthesizeStep(step_id="answer", type="synthesize", purpose="Compare evidence"),
])
USAGE = {"prompt_tokens": 20, "completion_tokens": 10}


def _candidate(document, content, chunk_id):
    return {
        "chunk_id": chunk_id, "document": document, "page": None,
        "section": "Runbook", "content": content,
    }


def test_named_document_comparison_excludes_unrelated_runbook():
    candidates = [
        _candidate("payment-incident-runbook.md", "payment response", "i"),
        _candidate("service-ownership.md", "Mercury team", "o"),
        _candidate("settlement-runbook.pdf", "settlement batches", "s"),
    ]
    selected = _restrict_to_named_documents(
        "Compare the severity-one payment incident runbook and service ownership guide",
        candidates,
    )
    assert {item["document"] for item in selected} == {
        "payment-incident-runbook.md", "service-ownership.md",
    }


def test_named_document_comparison_keeps_current_versioned_policy():
    candidates = [
        _candidate("payment-incident-runbook.md", "incident response", "i"),
        _candidate("service-ownership.md", "Mercury ownership", "o"),
        _candidate("payment-retry-policy-v2.md", "two retries", "p"),
        _candidate("settlement-runbook.pdf", "settlement batches", "s"),
    ]
    selected = _restrict_to_named_documents(
        "Compare the payment incident runbook, service ownership guide, "
        "and current payment retry policy",
        candidates,
    )
    assert {item["document"] for item in selected} == {
        "payment-incident-runbook.md", "service-ownership.md",
        "payment-retry-policy-v2.md",
    }


def test_explicit_single_document_title_excludes_unrelated_sources():
    candidates = [
        _candidate("payment-incident-runbook.md", "on-call response", "i"),
        _candidate("service-ownership.md", "Mercury owner", "o"),
    ]
    selected = _restrict_to_named_documents(
        "According to the payment incident runbook, who responds?", candidates,
    )
    assert [item["document"] for item in selected] == [
        "payment-incident-runbook.md",
    ]


def test_workflow_compares_two_documents_and_records_states():
    with (
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None), USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
        patch("app.agents.workflow.search_chunks", side_effect=[
            [_candidate("incident.md", "Validate settlement totals before recovery.", "i")],
            [_candidate("owners.md", "Mercury team owns the payments platform.", "o")],
        ]) as search,
        patch("app.agents.workflow.synthesize_findings", return_value=(
            SynthesisDraft(findings=[
                Finding(
                    deliverable_index=0, text="Validate settlement totals before recovery.",
                    source_ids=["S1"],
                ),
                Finding(
                    deliverable_index=1, text="Mercury owns payments.",
                    source_ids=["S2"],
                ),
            ]),
            {"prompt_tokens": 100, "completion_tokens": 30},
        )),
    ):
        result = run_planned_answer(QUESTION)

    assert result.state == "completed"
    assert {citation.document for citation in result.citations} == {"incident.md", "owners.md"}
    assert [event.state for event in result.trace] == [
        "received", "analyzing", "planning", "searching", "searched",
        "searching", "searched", "evidence_selected", "synthesizing", "completed",
    ]
    assert result.usage.model_calls == 5
    assert search.call_args_list[0].kwargs["scope"].as_of == search.call_args_list[1].kwargs["scope"].as_of


def test_workflow_returns_clarification_without_searching():
    with (
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(
                needs_clarification=True, goal=None,
                clarification_question="What goal or situation do you mean?",
            ), USAGE,
        )),
        patch("app.agents.workflow.plan_goal") as planner,
        patch("app.agents.workflow.search_chunks") as search,
    ):
        result = run_planned_answer("What should I do next?")

    assert result.state == "clarification"
    assert result.citations == []
    assert result.plan is None
    assert result.usage.model_calls == 1
    planner.assert_not_called()
    search.assert_not_called()


def test_workflow_stops_before_exceeding_model_call_budget():
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"workflow_max_model_calls": 3})
    with (
        patch("app.agents.workflow.get_settings", return_value=settings),
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None), USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
        patch("app.agents.workflow.search_chunks", return_value=[
            _candidate("incident.md", "A recovery fact.", "i"),
        ]) as search,
    ):
        with pytest.raises(WorkflowRunError) as captured:
            run_planned_answer(QUESTION)

    assert isinstance(captured.value.cause, WorkflowBudgetExceeded)
    assert captured.value.trace[-1].state == "failed"
    assert search.call_count == 1


def test_workflow_stops_when_token_budget_is_exceeded():
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"workflow_max_tokens": 40})
    with (
        patch("app.agents.workflow.get_settings", return_value=settings),
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None), USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
        patch("app.agents.workflow.search_chunks") as search,
    ):
        with pytest.raises(WorkflowRunError) as captured:
            run_planned_answer(QUESTION)

    assert isinstance(captured.value.cause, WorkflowBudgetExceeded)
    search.assert_not_called()


def test_runtime_budget_rejects_an_expired_workflow():
    from app.core.config import get_settings

    settings = get_settings()
    budget = _Budget(settings, perf_counter() - settings.workflow_max_runtime_seconds - 1)
    with pytest.raises(WorkflowBudgetExceeded, match="runtime"):
        budget.call()
