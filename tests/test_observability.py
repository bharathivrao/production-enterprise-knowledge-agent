import json
import logging
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.guardrails.auth import get_actor
from app.main import app
from app.observability import SafeJSONFormatter


def test_request_id_is_validated_and_returned():
    request_id = str(uuid4())
    client = TestClient(app)
    assert client.get(
        "/health/liveness", headers={"X-Request-ID": request_id},
    ).headers["x-request-id"] == request_id
    assert client.get(
        "/health/liveness", headers={"X-Request-ID": "token=secret"},
    ).headers["x-request-id"] != "token=secret"


def test_metrics_require_authentication():
    test_actor = app.dependency_overrides.pop(get_actor, None)
    try:
        assert TestClient(app).get("/metrics").status_code == 401
    finally:
        if test_actor is not None:
            app.dependency_overrides[get_actor] = test_actor
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "knowledge_agent_http_requests_total" in response.text


def test_json_log_formatter_omits_interpolated_sensitive_values():
    record = logging.LogRecord(
        "test", logging.ERROR, __file__, 1, "failed for %s", ("private prompt",), None,
    )
    payload = json.loads(SafeJSONFormatter().format(record))
    assert payload["event"] == "failed for %s"
    assert "private prompt" not in json.dumps(payload)


def test_lifespan_closes_database_model_and_reranker():
    with (
        patch("app.main.model_client.start") as start_model,
        patch("app.main.start_database_pool") as start_database,
        patch("app.main.close_database_pool") as close_database,
        patch("app.main.close_reranker") as close_reranker,
        patch("app.main.model_client.close") as close_model,
    ):
        with TestClient(app):
            pass
    start_model.assert_called_once()
    start_database.assert_called_once()
    close_database.assert_called_once()
    close_reranker.assert_called_once()
    close_model.assert_called_once()
