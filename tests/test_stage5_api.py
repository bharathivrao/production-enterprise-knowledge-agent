from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.workflow import WorkflowEvent, WorkflowRunError
from app.main import app
from app.tools.dispatcher import ToolError


client = TestClient(app)


def test_tool_endpoint_is_opt_in_and_rejects_caller_scope():
    response = client.post(
        "/ask/tools", json={"query": "Find policy", "tenant_id": "other"},
    )
    assert response.status_code == 422


def test_tool_endpoint_returns_controlled_error_and_redacted_trace():
    trace = [
        WorkflowEvent(
            state="tool_failed", elapsed_ms=1, tool_name="read_document_chunks",
            tool_status="not_found", argument_summary={"chunk_count": 1},
        ),
        WorkflowEvent(state="failed", elapsed_ms=2),
    ]
    with patch(
        "app.api.query.run_tool_answer",
        side_effect=WorkflowRunError(
            ToolError("not_found", "One or more chunks were not available"), trace,
        ),
    ):
        response = client.post("/ask/tools", json={"query": "Find policy"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["message"] == "The tool request could not be completed."
    assert detail["trace"][0]["argument_summary"] == {"chunk_count": 1}
    assert "chunk_ids" not in str(detail)
