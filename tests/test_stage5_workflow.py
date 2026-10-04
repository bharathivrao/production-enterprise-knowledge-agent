from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.goal_analyzer import Goal, GoalAnalysis
from app.agents.critic import EvidenceReview, FindingReview
from app.agents.planner import Plan, SearchStep, SynthesizeStep
from app.agents.synthesizer import Finding, SynthesisDraft
from app.agents.tool_selector import SelectedTool
from app.agents.workflow import WorkflowRunError, run_tool_answer
from app.tools.dispatcher import ToolError, ToolObservation


GOAL = Goal(
    objective="Compare incident response and ownership",
    entities=["incident", "platform"],
    deliverables=["incident response", "platform ownership"],
    constraints=[],
)
PLAN = Plan(goal=GOAL, steps=[
    SearchStep(step_id="s1", type="search", purpose="Find incident response",
               query="incident responder", deliverable_index=0),
    SearchStep(step_id="s2", type="search", purpose="Find platform ownership",
               query="platform owner", deliverable_index=1),
    SynthesizeStep(step_id="answer", type="synthesize", purpose="Cited comparison"),
])
USAGE = {"prompt_tokens": 20, "completion_tokens": 10}


def test_tool_workflow_selects_scoped_read_and_cites_both_documents():
    ids = [uuid4(), uuid4()]
    previews = [
        {"chunk_id": str(ids[0]), "document": "incident.md", "page": None,
         "section": "Response", "preview": "On-call engineer responds."},
        {"chunk_id": str(ids[1]), "document": "ownership.md", "page": None,
         "section": "Owner", "preview": "Mercury owns the platform."},
    ]
    read = [
        {**previews[0], "content": "The on-call engineer responds to incidents."},
        {**previews[1], "content": "Mercury owns the platform."},
    ]
    dispatcher = MagicMock()
    dispatcher.execute.side_effect = [
        ToolObservation("search_documents", [previews[0]], 1.0),
        ToolObservation("search_documents", [previews[1]], 1.0),
        ToolObservation("read_document_chunks", read, 1.0),
    ]
    with (
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None),
            USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
        patch("app.agents.workflow.ToolDispatcher", return_value=dispatcher) as boundary,
        patch("app.agents.workflow.select_tool", return_value=(
            SelectedTool(tool="read_document_chunks", chunk_ids=ids), USAGE,
        )),
        patch("app.agents.workflow.synthesize_findings", return_value=(
            SynthesisDraft(findings=[
                Finding(deliverable_index=0, text="On-call responds.", source_ids=["S1"]),
                Finding(deliverable_index=1, text="Mercury owns it.", source_ids=["S2"]),
            ]), USAGE,
        )),
        patch("app.agents.workflow.check_evidence", return_value=(
            EvidenceReview(findings=[
                FindingReview(deliverable_index=0, verdict="supported", reason="cited evidence"),
                FindingReview(deliverable_index=1, verdict="supported", reason="cited evidence"),
            ]), USAGE,
        )),
    ):
        result = run_tool_answer("Compare incident.md and ownership.md")
    assert result.state == "completed"
    assert {citation.document for citation in result.citations} == {
        "incident.md", "ownership.md",
    }
    assert result.usage.model_calls == 7
    assert [call.args[0] for call in dispatcher.execute.call_args_list] == [
        "search_documents", "search_documents", "read_document_chunks",
    ]
    assert boundary.call_args.args[0].as_of is not None
    assert boundary.call_args.kwargs["max_calls"] == 6
    assert any(event.state == "read" and event.result_count == 2 for event in result.trace)
    assert all("query" not in event.model_dump(exclude_none=True)
               for event in result.trace)


def test_tool_failure_returns_redacted_trace():
    dispatcher = MagicMock()
    dispatcher.execute.side_effect = ToolError("not_found", "One or more chunks were not available")
    with (
        patch("app.agents.workflow.analyze_goal", return_value=(
            GoalAnalysis(needs_clarification=False, goal=GOAL, clarification_question=None),
            USAGE,
        )),
        patch("app.agents.workflow.plan_goal", return_value=(PLAN, USAGE)),
        patch("app.agents.workflow.ToolDispatcher", return_value=dispatcher),
    ):
        with pytest.raises(WorkflowRunError) as captured:
            run_tool_answer("Compare incident.md and ownership.md")
    assert captured.value.trace[-2].state == "tool_failed"
    assert captured.value.trace[-2].tool_status == "not_found"
    assert captured.value.trace[-1].state == "failed"
