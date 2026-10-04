from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.planner import InvalidPlan
from app.agents.workflow import WorkflowBudgetExceeded, WorkflowEvent, WorkflowRunError
from app.main import app


client = TestClient(app)


def test_planned_endpoint_returns_clarification_trace():
    with patch("app.api.query.run_planned_answer", return_value={
        "state": "clarification",
        "answer": "What goal or situation do you mean?",
        "citations": [], "goal": None, "plan": None,
        "trace": [
            {"state": "received", "elapsed_ms": 0.1},
            {"state": "clarification", "elapsed_ms": 1.0},
        ],
        "usage": {"model_calls": 1, "tokens": 30, "elapsed_ms": 1.0},
        "metadata": {
            "goal_prompt_version": "4.0.0", "plan_prompt_version": "4.0.0",
            "synthesis_prompt_version": "4.0.0",
            "generation_model": "qwen3:4b", "embedding_model": "embeddinggemma",
            "retrieval_method": "vector", "max_steps": 4, "max_model_calls": 6,
            "max_tokens": 12000, "max_runtime_seconds": 600,
        },
    }) as workflow:
        response = client.post("/ask/planned", json={"query": "What should I do next?"})

    assert response.status_code == 200
    assert response.json()["state"] == "clarification"
    workflow.assert_called_once_with(
        "What should I do next?", top_k=3,
        scope=workflow.call_args.kwargs["scope"],
    )


def test_planned_endpoint_rejects_user_supplied_scope():
    response = client.post(
        "/ask/planned",
        json={"query": "Compare policies", "tenant_id": "another-tenant"},
    )
    assert response.status_code == 422


def test_invalid_model_plan_returns_controlled_error_with_trace():
    trace = [WorkflowEvent(state="planning", elapsed_ms=1.0)]
    trace.append(WorkflowEvent(state="failed", elapsed_ms=2.0))
    with patch(
        "app.api.query.run_planned_answer",
        side_effect=WorkflowRunError(InvalidPlan("unknown step"), trace),
    ):
        response = client.post("/ask/planned", json={"query": "Compare policies"})
    assert response.status_code == 502
    assert [event["state"] for event in response.json()["detail"]["trace"]] == [
        "planning", "failed",
    ]


def test_budget_error_returns_timeout_with_trace():
    trace = [WorkflowEvent(state="failed", elapsed_ms=4.0)]
    with patch(
        "app.api.query.run_planned_answer",
        side_effect=WorkflowRunError(WorkflowBudgetExceeded("token budget"), trace),
    ):
        response = client.post("/ask/planned", json={"query": "Compare policies"})
    assert response.status_code == 504
    assert response.json()["detail"]["trace"][0]["state"] == "failed"
