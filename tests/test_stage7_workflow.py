from unittest.mock import patch
from uuid import uuid4

from app.agents.critic import EvidenceReview, FindingReview
from app.agents.goal_analyzer import Goal, GoalAnalysis
from app.agents.planner import Plan, SearchStep, SynthesizeStep
from app.agents.synthesizer import Finding, SynthesisDraft
from app.agents.tool_selector import SelectedTool
from app.agents.workflow import (
    ABSTENTION, _enforce_named_source_coverage, run_planned_answer, run_tool_answer,
)
from app.tools.dispatcher import ToolObservation


GOAL = Goal(
    objective="Find the payments owner", entities=["payments"],
    deliverables=["payments owner"], constraints=[],
)
PLAN = Plan(goal=GOAL, steps=[
    SearchStep(step_id="s1", type="search", purpose="Find ownership",
               query="payments platform owner", deliverable_index=0),
    SynthesizeStep(step_id="answer", type="synthesize", purpose="Answer question"),
])
USAGE = {"prompt_tokens": 12, "completion_tokens": 8}
WEAK = SynthesisDraft(findings=[
    Finding(deliverable_index=0, text="Mercury owns payments.", source_ids=["S1"]),
])
STRONG = SynthesisDraft(findings=[
    Finding(deliverable_index=0, text="Atlas owns payments.", source_ids=["S2"]),
])
WEAK_REVIEW = EvidenceReview(findings=[
    FindingReview(deliverable_index=0, verdict="contradicted", reason="wrong team"),
], search_query="current payments team ownership")
GOOD_REVIEW = EvidenceReview(findings=[
    FindingReview(deliverable_index=0, verdict="supported", reason="direct match"),
])


def candidate(name, content, id):
    return {"chunk_id": id, "document": name, "page": None,
            "section": "Owner", "content": content}


def common_patches():
    return (
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None),
            USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
    )


def test_weak_answer_improves_after_one_novel_scoped_search():
    first = candidate("old.md", "The platform owner is not Mercury.", "a")
    second = candidate("new.md", "Atlas owns payments.", "b")
    analyzer, planner = common_patches()
    with (analyzer, planner,
          patch("app.agents.workflow.search_chunks", side_effect=[[first], [second]]) as search,
          patch("app.agents.workflow.synthesize_findings", side_effect=[
              (WEAK, USAGE), (STRONG, USAGE),
          ]),
          patch("app.agents.workflow.check_evidence", side_effect=[
              (WEAK_REVIEW, USAGE), (GOOD_REVIEW, USAGE),
          ])):
        result = run_planned_answer("Who owns payments?")
    assert "Atlas owns payments" in result.answer
    assert [item.document for item in result.citations] == ["new.md"]
    assert search.call_count == 2
    assert search.call_args_list[0].kwargs["scope"] == search.call_args_list[1].kwargs["scope"]
    assert [item.state for item in result.trace].count("correction_searching") == 1
    assert result.usage.model_calls == 8


def test_failed_second_check_yields_abstention_without_second_search():
    first = candidate("old.md", "Mercury does not own payments.", "a")
    repeated = WEAK_REVIEW.model_copy(update={"search_query": "payments platform owner"})
    analyzer, planner = common_patches()
    with (analyzer, planner,
          patch("app.agents.workflow.search_chunks", return_value=[first]) as search,
          patch("app.agents.workflow.synthesize_findings", return_value=(WEAK, USAGE)),
          patch("app.agents.workflow.check_evidence", side_effect=[
              (repeated, USAGE), (repeated, USAGE),
          ])):
        result = run_planned_answer("Who owns payments?")
    assert result.answer == ABSTENTION
    assert result.citations == []
    assert search.call_count == 1
    assert [item.state for item in result.trace].count("revising") == 1


def test_checker_failure_does_not_release_unchecked_draft():
    analyzer, planner = common_patches()
    with (analyzer, planner,
          patch("app.agents.workflow.search_chunks", return_value=[
              candidate("old.md", "Mercury owns payments.", "a"),
          ]),
          patch("app.agents.workflow.synthesize_findings", return_value=(WEAK, USAGE)),
          patch("app.agents.workflow.check_evidence", side_effect=RuntimeError("model down"))):
        result = run_planned_answer("Who owns payments?")
    assert result.answer == ABSTENTION
    assert result.citations == []
    assert any(item.state == "check_failed" for item in result.trace)


def test_explicit_document_requirement_overrides_permissive_model_review():
    goal = Goal(
        objective="Incident response", entities=["payments"],
        deliverables=["incident responder"], constraints=[],
    )
    plan = Plan(goal=goal, steps=[
        SearchStep(step_id="s1", type="search", purpose="Find responder",
                   query="payment incident runbook responder", deliverable_index=0),
        SynthesizeStep(step_id="answer", type="synthesize", purpose="Answer"),
    ])
    candidates = [
        candidate("payment-incident-runbook.md", "On-call responds.", "a"),
        candidate("service-ownership.md", "Mercury owns payments.", "b"),
    ]
    draft = SynthesisDraft(findings=[
        Finding(deliverable_index=0, text="Mercury responds.", source_ids=["S2"]),
    ])
    review, feedback = _enforce_named_source_coverage(
        "According to the payment incident runbook, who responds?",
        plan, candidates, draft,
        {"S1": {"document": "payment-incident-runbook.md"},
         "S2": {"document": "service-ownership.md"}},
        GOOD_REVIEW,
    )
    assert review.findings[0].verdict == "incomplete"
    assert "payment-incident-runbook.md" in feedback[0]
    assert review.search_query is not None


def test_tool_correction_reads_new_scoped_chunk_before_revising():
    first_id, second_id = uuid4(), uuid4()
    first = candidate("old.md", "Mercury does not own payments.", str(first_id))
    second = candidate("new.md", "Atlas owns payments.", str(second_id))
    calls = []

    class Dispatcher:
        def __init__(self, scope, *, max_calls, max_elapsed_seconds):
            self.scope = scope
            assert max_calls == 6

        def execute(self, name, arguments):
            calls.append((name, arguments))
            values = [[{**first, "preview": first["content"]}], [first],
                      [{**second, "preview": second["content"]}], [second]]
            return ToolObservation(name=name, result=values[len(calls) - 1], elapsed_ms=1)

    analyzer, planner = common_patches()
    with (analyzer, planner,
          patch("app.agents.workflow.ToolDispatcher", Dispatcher),
          patch("app.agents.workflow.select_tool", return_value=(
              SelectedTool(tool="read_document_chunks", chunk_ids=[first_id]), USAGE,
          )),
          patch("app.agents.workflow.synthesize_findings", side_effect=[
              (WEAK, USAGE), (STRONG, USAGE),
          ]),
          patch("app.agents.workflow.check_evidence", side_effect=[
              (WEAK_REVIEW, USAGE), (GOOD_REVIEW, USAGE),
          ])):
        result = run_tool_answer("Who owns payments?")
    assert [name for name, _ in calls] == [
        "search_documents", "read_document_chunks",
        "search_documents", "read_document_chunks",
    ]
    assert result.citations[0].document == "new.md"
