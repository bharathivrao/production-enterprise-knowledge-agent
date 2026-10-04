from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.agents.goal_analyzer import Goal, GoalAnalysis, InvalidGoalAnalysis, analyze_goal
from app.agents.planner import (
    InvalidPlan, PlanDraft, plan_goal, validate_plan,
)


def _goal(*, three_deliverables=False):
    return Goal(
        objective="Compare payment incident recovery and ownership",
        entities=["payments", "incident commander"],
        deliverables=[
            "incident recovery", "platform ownership",
            *(["recovery validation"] if three_deliverables else []),
        ],
        constraints=["use current documents"],
    )


def _draft(*queries):
    return PlanDraft(queries=list(queries))


def test_goal_analysis_requires_explicit_clarification_or_actionable_goal():
    clarification = GoalAnalysis(
        needs_clarification=True, goal=None,
        clarification_question="What goal or situation do you mean?",
    )
    assert clarification.goal is None
    actionable = GoalAnalysis(
        needs_clarification=False, goal=_goal(), clarification_question="",
    )
    assert actionable.clarification_question is None
    missing_goal = GoalAnalysis(
        needs_clarification=False, goal=None, clarification_question=None,
    )
    assert missing_goal.needs_clarification is True
    assert missing_goal.clarification_question.endswith("?")
    with pytest.raises(ValidationError):
        GoalAnalysis(
            needs_clarification=True, goal=_goal(),
            clarification_question="What goal do you mean?",
        )


def test_goal_analyzer_rejects_invalid_model_output():
    with patch("app.agents.goal_analyzer.model_client.chat", return_value={
        "message": {"content": '{"needs_clarification":"not a boolean","goal":null}'},
    }):
        with pytest.raises(InvalidGoalAnalysis):
            analyze_goal("Compare payment runbooks")


def test_comparison_requires_distinct_search_steps_and_final_synthesis():
    with pytest.raises(InvalidPlan, match="every requested deliverable"):
        validate_plan(
            _draft("payment incident recovery"), _goal(),
            "Compare payment incident recovery and ownership", max_steps=4,
        )

    plan = validate_plan(
        _draft("payment incident recovery", "payments platform ownership"),
        _goal(), "Compare payment incident recovery and ownership", max_steps=4,
    )
    assert [step.type for step in plan.steps] == ["search", "search", "synthesize"]


def test_plan_rejects_unknown_step_duplicate_query_and_step_budget():
    with pytest.raises(ValidationError):
        PlanDraft.model_validate({
            "queries": ["payment incident"],
            "steps": [{"type": "delete", "purpose": "Delete a document"}],
        })
    with pytest.raises(InvalidPlan):
        validate_plan(
            _draft("payment incident", "payment incident"),
            _goal(), "Compare incident and ownership", max_steps=4,
        )
    with pytest.raises(InvalidPlan, match="step budget"):
        validate_plan(
            _draft("payment incident", "payments owner", "recovery validation"),
            _goal(three_deliverables=True), "Compare incident and ownership", max_steps=3,
        )


def test_planner_rejects_model_attempt_to_supply_other_step_types():
    bad_response = {
        "message": {"content": '{"queries":["payment incident"],'
                               '"steps":[{"type":"execute_sql"}]}'},
    }
    with patch("app.agents.planner.model_client.chat", return_value=bad_response):
        with pytest.raises(InvalidPlan):
            plan_goal(_goal(), "Compare payment incident and ownership", max_steps=4)
